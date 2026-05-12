"""End-to-end orchestration for the space intelligence pipeline.

Pipeline shape::

    sources/* -> normalized IntelligenceEvents
                 -> dedupe
                 -> persist to JSONL store
                 -> BriefingInput
                 -> summarizer (LLM)
                 -> deck (.pptx)
                 -> emailer

Each source is independently fault-tolerant: if launch ingestion fails the
news briefing still goes out, and vice versa. If both fail, we still emit a
"no major updates found" deck so the daily run never silently fails.

The legacy ``pipeline.run_pipeline`` API is preserved as a thin wrapper around
:func:`run_pipeline` here so :mod:`cli` keeps working unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from .config import AppConfig
from .core.dedupe import dedupe_events
from .core.models import BriefingInput, IntelligenceEvent
from .core.storage import append_events
from .deck import build_deck
from .email_sender import EmailError, send_briefing_email
from .models import Briefing
from .sources.launches import fetch_launch_events
from .sources.news import fetch_news_events
from .summarizer import SummarizerError, summarize_briefing_input

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    briefing: Briefing
    deck_path: Path
    emailed: bool
    email_error: str | None = None
    events: list[IntelligenceEvent] | None = None


def run_pipeline(
    cfg: AppConfig,
    *,
    briefing_date: date | None = None,
    skip_email: bool = False,
) -> PipelineResult:
    """Execute the full briefing pipeline.

    Email failures are non-fatal: the deck is always written to disk first so
    a transient SMTP error never loses the day's report. Source failures are
    also non-fatal as long as at least one source produced events (or no
    sources are enabled, in which case we emit an empty-but-valid deck).
    """
    target_date = briefing_date or date.today()
    logger.info("Starting briefing pipeline for %s", target_date.isoformat())

    events = _collect_events(cfg)

    deduped = dedupe_events(events)
    if len(deduped) != len(events):
        logger.info("Deduped %d -> %d event(s)", len(events), len(deduped))

    _persist_events(cfg.events_store_path, deduped)

    briefing_input = BriefingInput(
        generated_at=datetime.now(UTC),
        events=deduped,
    )

    try:
        briefing = summarize_briefing_input(
            cfg=cfg.llm,
            briefing_input=briefing_input,
            briefing_date=target_date,
        )
    except SummarizerError:
        logger.exception("Summarization failed")
        raise

    deck_path = build_deck(briefing, cfg.output_dir, events=deduped)

    emailed = False
    email_error: str | None = None
    if skip_email:
        logger.info("Skipping email send (skip_email=True).")
    elif not cfg.email.is_configured:
        email_error = "Email not configured; skipping send."
        logger.warning(email_error)
    else:
        try:
            send_briefing_email(cfg=cfg.email, briefing=briefing, deck_path=deck_path)
            emailed = True
        except EmailError as exc:
            email_error = str(exc)
            logger.exception("Failed to send briefing email (deck still saved at %s)", deck_path)

    return PipelineResult(
        briefing=briefing,
        deck_path=deck_path,
        emailed=emailed,
        email_error=email_error,
        events=deduped,
    )


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _collect_events(cfg: AppConfig) -> list[IntelligenceEvent]:
    events: list[IntelligenceEvent] = []

    if cfg.sources.enable_news:
        try:
            news_events = fetch_news_events(cfg)
            logger.info("News source: %d event(s)", len(news_events))
            events.extend(news_events)
        except Exception as exc:  # noqa: BLE001 - one source must not kill the run
            logger.warning("News source failed: %s", exc, exc_info=True)
    else:
        logger.info("News source disabled (ENABLE_NEWS_SOURCE=false).")

    if cfg.sources.enable_launch:
        try:
            launch_events = fetch_launch_events(cfg)
            logger.info("Launch source: %d event(s)", len(launch_events))
            events.extend(launch_events)
        except Exception as exc:  # noqa: BLE001 - launches are advisory
            logger.warning("Launch source failed: %s", exc, exc_info=True)
    else:
        logger.info("Launch source disabled (ENABLE_LAUNCH_SOURCE=false).")

    if not events:
        logger.warning("No events collected from any enabled source.")

    return events


def _persist_events(path: Path, events: list[IntelligenceEvent]) -> None:
    """Append today's events to the JSONL store. Best-effort — never fatal."""
    if not events:
        return
    try:
        append_events(path, events)
    except OSError as exc:
        logger.warning("Failed to persist events to %s: %s", path, exc)
