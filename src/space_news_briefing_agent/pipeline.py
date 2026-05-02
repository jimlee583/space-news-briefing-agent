"""End-to-end pipeline: collect -> summarize -> render -> email."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import AppConfig
from .deck import build_deck
from .email_sender import EmailError, send_briefing_email
from .models import Briefing
from .news import build_provider, collect_articles
from .summarizer import SummarizerError, summarize_briefing
from .topics import load_topics

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    briefing: Briefing
    deck_path: Path
    emailed: bool
    email_error: str | None = None


def run_pipeline(
    cfg: AppConfig,
    *,
    briefing_date: date | None = None,
    skip_email: bool = False,
) -> PipelineResult:
    """Run the full briefing pipeline and return the result.

    Email failures are non-fatal: the deck is always written to disk first, so a
    transient SMTP error never loses the day's report.
    """
    target_date = briefing_date or date.today()
    logger.info("Starting briefing pipeline for %s", target_date.isoformat())

    topics = load_topics(cfg.topics_file)
    provider = build_provider(cfg.news)

    articles_by_topic = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=cfg.news.lookback_hours,
        default_max_articles=cfg.news.max_articles_per_topic,
    )

    try:
        briefing = summarize_briefing(
            cfg=cfg.llm,
            articles_by_topic=articles_by_topic,
            briefing_date=target_date,
        )
    except SummarizerError:
        logger.exception("Summarization failed")
        raise

    deck_path = build_deck(briefing, cfg.output_dir)

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
    )
