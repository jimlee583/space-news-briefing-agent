"""LLM-backed summarization producing a structured `Briefing`.

Design choices:
* The prompt explicitly forbids hallucination and requires every cited fact to
  be grounded in the provided article corpus.
* We use OpenAI's structured-output mode (`responses.parse`) so the model
  is constrained to our Pydantic schema and we never have to JSON-parse by hand.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from openai import OpenAI

from .config import LLMConfig
from .models import Article, Briefing, CompanyBrief, NewsItem

logger = logging.getLogger(__name__)


class SummarizerError(RuntimeError):
    """Raised when the LLM call or response handling fails."""


# Tunables: keep article payloads small to control token cost, but rich enough
# for the model to write grounded summaries.
_MAX_ARTICLE_DESCRIPTION_CHARS = 600
_MAX_ARTICLE_CONTENT_CHARS = 1200


_SYSTEM_PROMPT = """You are a senior defense and space-industry analyst writing
a daily executive briefing. Your output will be turned directly into a
PowerPoint deck for executives, so be crisp, factual, and decision-relevant.

STRICT RULES — follow without exception:
1. Use ONLY the articles supplied in the user message. Do not invent facts,
   quotes, dollar amounts, dates, contract numbers, or program names that are
   not present in the supplied content.
2. If a topic has no supplied articles, say so explicitly in its
   `executive_summary` and leave its other lists empty.
3. Every `NewsItem.url` MUST be copied verbatim from a supplied article. Never
   fabricate URLs.
4. Prefer plain, neutral language. No marketing fluff. No emoji.
5. Every claim should be traceable to at least one supplied article.
6. `confidence` should reflect how strongly the supplied article(s) support
   the claim: "high" for primary-source reporting, "medium" for trade press
   summarizing other reporting, "low" for ambiguous or rumor-grade items.

CONTENT EMPHASIS — when present in the source articles, highlight:
- What changed in the last 24-48 hours
- Major announcements
- Contracts and awards (especially DoD / SDA / NRO / SSC)
- Launches and on-orbit events
- Spacecraft and satellite program updates
- Defense-space implications (national security, deterrence, allied posture)
- Supply chain and manufacturing implications
- Competitive positioning between primes and new-space entrants
"""


def summarize_briefing(
    *,
    cfg: LLMConfig,
    articles_by_topic: dict[str, list[Article]],
    briefing_date: date,
) -> Briefing:
    """Call the LLM and return a validated `Briefing`.

    If `articles_by_topic` is entirely empty we short-circuit with a deterministic
    "nothing to report" briefing so the deck still renders without burning tokens.
    """
    if not cfg.is_configured:
        raise SummarizerError("OPENAI_API_KEY is not configured.")

    total_articles = sum(len(v) for v in articles_by_topic.values())
    if total_articles == 0:
        logger.warning("No articles collected — emitting empty briefing without calling LLM.")
        return _empty_briefing(articles_by_topic, briefing_date)

    client = OpenAI(api_key=cfg.api_key)
    user_payload = _build_user_payload(articles_by_topic, briefing_date)

    logger.info(
        "Requesting summary from model=%s for %d article(s) across %d topic(s)",
        cfg.model,
        total_articles,
        len(articles_by_topic),
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

    _ensure_topic_coverage(briefing, articles_by_topic)
    _populate_source_list(briefing, articles_by_topic)

    logger.info(
        "Briefing built: %d company brief(s), %d source URL(s)",
        len(briefing.company_briefs),
        len(briefing.source_list),
    )
    return briefing


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _build_user_payload(
    articles_by_topic: dict[str, list[Article]],
    briefing_date: date,
) -> str:
    """Render the article corpus as a stable, easy-to-cite JSON blob."""
    payload: dict[str, Any] = {
        "briefing_date": briefing_date.isoformat(),
        "instructions": (
            "Produce a Briefing object covering every topic listed below, in the same order. "
            "If a topic has no articles, still include a CompanyBrief for it with an "
            "executive_summary that explicitly says no qualifying news was found in the "
            "lookback window, and leave its lists empty."
        ),
        "topics": [
            {
                "topic_name": topic_name,
                "article_count": len(articles),
                "articles": [_article_to_payload(a) for a in articles],
            }
            for topic_name, articles in articles_by_topic.items()
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _article_to_payload(article: Article) -> dict[str, Any]:
    return {
        "title": article.title,
        "source": article.source,
        "author": article.author,
        "url": article.url,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "query": article.query,
        "description": _truncate(article.description, _MAX_ARTICLE_DESCRIPTION_CHARS),
        "content": _truncate(article.content, _MAX_ARTICLE_CONTENT_CHARS),
    }


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _ensure_topic_coverage(
    briefing: Briefing, articles_by_topic: dict[str, list[Article]]
) -> None:
    """Guarantee one CompanyBrief per topic, even if the model omitted one."""
    by_name = {b.topic_name: b for b in briefing.company_briefs}
    ordered: list[CompanyBrief] = []
    for topic_name, articles in articles_by_topic.items():
        existing = by_name.get(topic_name)
        if existing is not None:
            ordered.append(existing)
            continue
        ordered.append(
            CompanyBrief(
                topic_name=topic_name,
                executive_summary=(
                    "No qualifying news was found in the lookback window."
                    if not articles
                    else "Summary unavailable — model did not produce a brief for this topic."
                ),
                top_items=[],
                implications=[],
                watch_items=[],
            )
        )
    briefing.company_briefs = ordered


def _populate_source_list(
    briefing: Briefing, articles_by_topic: dict[str, list[Article]]
) -> None:
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

    for articles in articles_by_topic.values():
        for article in articles:
            if article.url and article.url not in seen:
                seen.add(article.url)
                ordered.append(article.url)

    briefing.source_list = ordered


def _empty_briefing(
    articles_by_topic: dict[str, list[Article]], briefing_date: date
) -> Briefing:
    return Briefing(
        deck_title="Daily Space & Defense-Space News Briefing",
        briefing_date=briefing_date.isoformat(),
        cross_company_summary=(
            "No qualifying news was found in the lookback window for any tracked topic."
        ),
        company_briefs=[
            CompanyBrief(
                topic_name=name,
                executive_summary="No qualifying news was found in the lookback window.",
                top_items=[],
                implications=[],
                watch_items=[],
            )
            for name in articles_by_topic
        ],
        industry_themes=[],
        defense_space_implications=[],
        watch_items=[],
        source_list=[],
    )


# Re-export for callers that want the symbol without reaching into models
__all__ = ["NewsItem", "summarize_briefing", "SummarizerError"]
