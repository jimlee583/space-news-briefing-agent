"""LLM-backed summarization producing a structured ``Briefing``.

The summarizer now accepts a ``BriefingInput`` (a heterogeneous list of
normalized ``IntelligenceEvent`` objects) instead of a topic-keyed dict of
news ``Article`` records, so downstream sources (launches, FCC filings,
SAM.gov, …) can flow through the same prompt path.

Design choices:
* The prompt explicitly forbids hallucination and requires every cited fact
  to be grounded in the provided event corpus.
* News and launch events are passed in separate payload sections so the
  model can clearly distinguish "what happened" from "what's scheduled".
* We use OpenAI's structured-output mode (``responses.parse``) so the model
  is constrained to our Pydantic schema and we never have to JSON-parse by
  hand.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from datetime import date
from typing import Any

from openai import OpenAI

from .config import LLMConfig
from .core.models import BriefingInput, IntelligenceEvent, LaunchEvent
from .models import Article, Briefing, CompanyBrief, NewsItem

logger = logging.getLogger(__name__)


class SummarizerError(RuntimeError):
    """Raised when the LLM call or response handling fails."""


# Keep payloads small to control token cost while still grounding the model.
_MAX_SUMMARY_CHARS = 600
_MAX_RAW_CONTENT_CHARS = 1200


_SYSTEM_PROMPT = """You are a senior defense and space-industry analyst writing
a daily executive briefing. Your output will be turned directly into a
PowerPoint deck for executives, so be crisp, factual, and decision-relevant.

You are creating an executive space and defense-space intelligence briefing.
Inputs include MULTIPLE source types: news articles AND scheduled future
launches. Treat them differently:

* News events describe things that have already happened or been announced.
* Launch events are SCHEDULED future activity — never describe them as
  having occurred. Use phrasing like "scheduled for", "planned NET", etc.

STRICT RULES — follow without exception:
1. Use ONLY the events supplied in the user message. Do not invent facts,
   quotes, dollar amounts, dates, contract numbers, or program names that
   are not present in the supplied content.
2. If a topic / company has no supplied events, say so explicitly in its
   ``executive_summary`` and leave its other lists empty.
3. Every ``NewsItem.url`` MUST be copied verbatim from a supplied event.
   Never fabricate URLs. If an event has no URL, do not include it as a
   NewsItem.
4. Prefer plain, neutral language. No marketing fluff. No emoji.
5. Every claim should be traceable to at least one supplied event.
6. ``confidence`` reflects how strongly the supplied source(s) support the
   claim: "high" for primary-source reporting, "medium" for trade press
   summarizing other reporting, "low" for ambiguous, scheduled, or
   rumor-grade items.

CONTENT EMPHASIS — when present in the source events, highlight:
- What changed in the last 24-48 hours (news only)
- Major announcements and contracts/awards (especially DoD / SDA / NRO / SSC)
- Cross-company implications and competitive positioning
- Defense-space implications (national security, deterrence, allied posture)
- Upcoming launches relevant to tracked entities (use industry_themes or
  watch_items, NOT cross_company_summary, to call out scheduled launches)
- Watch items: monitorable items over the next few days/weeks

If no events are supplied, return a Briefing whose ``cross_company_summary``
states clearly that no qualifying intelligence was found in the lookback
window, and leave all other lists empty.
"""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def summarize_briefing_input(
    *,
    cfg: LLMConfig,
    briefing_input: BriefingInput,
    briefing_date: date,
) -> Briefing:
    """LLM-summarize a ``BriefingInput`` into a structured ``Briefing``.

    Short-circuits to a deterministic empty briefing when there are no
    events, so the deck still renders without burning tokens.
    """
    if not cfg.is_configured:
        raise SummarizerError(
            "OPENAI_API_KEY is not configured. Edit your .env and replace the "
            "placeholder (e.g. 'sk-...') with a real key from "
            "https://platform.openai.com/account/api-keys."
        )

    events = briefing_input.events
    topics_seen = _collect_topics(events)

    if not events:
        logger.warning("No events supplied — emitting empty briefing without calling LLM.")
        return _empty_briefing(topics_seen, briefing_date)

    client = OpenAI(api_key=cfg.api_key)
    user_payload = _build_event_payload(briefing_input, briefing_date)

    logger.info(
        "Requesting summary from model=%s for %d event(s) (%d news, %d launch)",
        cfg.model,
        len(events),
        sum(1 for e in events if e.source_type == "news"),
        sum(1 for e in events if e.source_type == "launch"),
    )

    try:
        response = client.responses.parse(
            model=cfg.model,
            input=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            text_format=Briefing,
        )
    except Exception as exc:  # noqa: BLE001 - surface any client/SDK error uniformly
        raise SummarizerError(f"LLM call failed: {exc}") from exc

    briefing = response.output_parsed
    if briefing is None:
        raise SummarizerError("LLM returned no parsed output.")

    briefing.briefing_date = briefing_date.isoformat()
    if not briefing.deck_title:
        briefing.deck_title = "Daily Space & Defense-Space News Briefing"

    _ensure_topic_coverage(briefing, topics_seen)
    _populate_source_list(briefing, events)

    logger.info(
        "Briefing built: %d company brief(s), %d source URL(s)",
        len(briefing.company_briefs),
        len(briefing.source_list),
    )
    return briefing


def summarize_briefing(
    *,
    cfg: LLMConfig,
    articles_by_topic: dict[str, list[Article]],
    briefing_date: date,
) -> Briefing:
    """Backwards-compatible wrapper that converts the legacy article dict
    into a ``BriefingInput`` and delegates to :func:`summarize_briefing_input`.

    Kept for callers that haven't migrated to the event-based API yet.
    """
    from datetime import UTC, datetime

    from .core.normalize import normalize_news_articles

    flat_dicts: list[dict[str, Any]] = []
    for topic_name, articles in articles_by_topic.items():
        for article in articles:
            flat_dicts.append({**article.model_dump(mode="python"), "topic_name": topic_name})

    events = normalize_news_articles(flat_dicts)
    bi = BriefingInput(generated_at=datetime.now(UTC), events=events)
    return summarize_briefing_input(cfg=cfg, briefing_input=bi, briefing_date=briefing_date)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _collect_topics(events: list[IntelligenceEvent]) -> list[str]:
    """Stable-ordered list of topic labels seen across ``events``."""
    seen: OrderedDict[str, None] = OrderedDict()
    for event in events:
        for t in event.topics:
            if t and t not in seen:
                seen[t] = None
    return list(seen.keys())


def _build_event_payload(briefing_input: BriefingInput, briefing_date: date) -> str:
    """Render the event corpus as a stable, easy-to-cite JSON blob."""
    news = [_event_to_payload(e) for e in briefing_input.events if e.source_type == "news"]
    launches = [_launch_to_payload(e) for e in briefing_input.events if isinstance(e, LaunchEvent)]

    payload: dict[str, Any] = {
        "briefing_date": briefing_date.isoformat(),
        "instructions": (
            "Produce a Briefing object grounded in the provided events. "
            "Distinguish news (already happened) from upcoming launches "
            "(scheduled, future). Group company-relevant news under "
            "company_briefs by topic_name. Use industry_themes or watch_items "
            "for cross-cutting items, including upcoming launches that affect "
            "tracked entities."
        ),
        "topics_seen": _collect_topics(briefing_input.events),
        "news_events": news,
        "launch_events": launches,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _event_to_payload(event: IntelligenceEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "source_type": event.source_type,
        "source_name": event.source_name,
        "title": event.title,
        "summary": _truncate(event.summary or "", _MAX_SUMMARY_CHARS),
        "url": event.url,
        "published_at": event.published_at.isoformat() if event.published_at else None,
        "topics": event.topics,
        "entities": event.entities,
        "tags": event.tags,
        "author": getattr(event, "author", None),
        "content": _truncate(
            (event.raw.get("content") if isinstance(event.raw, dict) else "") or "",
            _MAX_RAW_CONTENT_CHARS,
        ),
    }


def _launch_to_payload(event: LaunchEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "source_type": event.source_type,
        "source_name": event.source_name,
        "title": event.title,
        "summary": _truncate(event.summary or "", _MAX_SUMMARY_CHARS),
        "url": event.url,
        "event_date": event.event_date.isoformat() if event.event_date else None,
        "launch_provider": event.launch_provider,
        "vehicle": event.vehicle,
        "payload": event.payload,
        "launch_site": event.launch_site,
        "mission_status": event.mission_status,
        "entities": event.entities,
        "tags": event.tags,
    }


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_topic_coverage(briefing: Briefing, topics_seen: list[str]) -> None:
    """Guarantee one CompanyBrief per topic, even if the model omitted one."""
    if not topics_seen:
        return
    by_name = {b.topic_name: b for b in briefing.company_briefs}
    ordered: list[CompanyBrief] = []
    for topic_name in topics_seen:
        existing = by_name.get(topic_name)
        if existing is not None:
            ordered.append(existing)
            continue
        ordered.append(
            CompanyBrief(
                topic_name=topic_name,
                executive_summary=(
                    "Summary unavailable — model did not produce a brief for this topic."
                ),
                top_items=[],
                implications=[],
                watch_items=[],
            )
        )
    # Preserve any extra briefs the model added that we didn't expect.
    extra = [b for b in briefing.company_briefs if b.topic_name not in set(topics_seen)]
    briefing.company_briefs = ordered + extra


def _populate_source_list(briefing: Briefing, events: list[IntelligenceEvent]) -> None:
    """Backfill source_list from cited NewsItems and the source corpus.

    Preserves order of first appearance so the deck reads naturally.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    for brief in briefing.company_briefs:
        for item in brief.top_items:
            if item.url and item.url not in seen:
                seen.add(item.url)
                ordered.append(item.url)

    for event in events:
        if event.url and event.url not in seen:
            seen.add(event.url)
            ordered.append(event.url)

    briefing.source_list = ordered


def _empty_briefing(topics_seen: list[str], briefing_date: date) -> Briefing:
    return Briefing(
        deck_title="Daily Space & Defense-Space News Briefing",
        briefing_date=briefing_date.isoformat(),
        cross_company_summary=(
            "No major updates found: no qualifying intelligence events were "
            "available in the lookback window."
        ),
        company_briefs=[
            CompanyBrief(
                topic_name=name,
                executive_summary="No qualifying news was found in the lookback window.",
                top_items=[],
                implications=[],
                watch_items=[],
            )
            for name in topics_seen
        ],
        industry_themes=[],
        defense_space_implications=[],
        watch_items=[],
        source_list=[],
    )


# Re-export for callers that want the symbol without reaching into models
__all__ = [
    "NewsItem",
    "SummarizerError",
    "summarize_briefing",
    "summarize_briefing_input",
]
