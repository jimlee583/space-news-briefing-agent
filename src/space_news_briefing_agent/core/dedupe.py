"""Cross-source deduplication for ``IntelligenceEvent``.

Sources frequently overlap (the same Rocket Lab launch shows up as a news
article AND as a Launch Library 2 entry). We dedupe on:

1. Canonicalized URL — the strongest signal when both sides cite the same
   article.
2. Normalized title — catches the "same story, different host" case.

When two events collide, we keep the one with the higher
``IntelligenceEvent.completeness_score`` and merge in any extra entities/tags
from the loser so we don't drop signal.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from .models import IntelligenceEvent

logger = logging.getLogger(__name__)

_TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "mkt_", "icid", "ito")


def dedupe_events(events: Iterable[IntelligenceEvent]) -> list[IntelligenceEvent]:
    """Return ``events`` with URL- and title-duplicates collapsed.

    Stable: input order is preserved for the survivors.
    """
    by_url: dict[str, int] = {}
    by_title: dict[str, int] = {}
    survivors: list[IntelligenceEvent] = []

    for incoming in events:
        canonical = _canonical_url(incoming.url) if incoming.url else ""
        norm_title = _normalize_title(incoming.title)

        existing_idx: int | None = None
        if canonical and canonical in by_url:
            existing_idx = by_url[canonical]
        elif norm_title and norm_title in by_title:
            existing_idx = by_title[norm_title]

        if existing_idx is None:
            survivors.append(incoming)
            idx = len(survivors) - 1
            if canonical:
                by_url[canonical] = idx
            if norm_title:
                by_title[norm_title] = idx
            continue

        # Collision: keep the more complete event, merge enrichment fields.
        existing = survivors[existing_idx]
        winner, loser = _pick_winner(existing, incoming)
        merged = _merge_enrichment(winner, loser)
        survivors[existing_idx] = merged

        if canonical:
            by_url[canonical] = existing_idx
        if norm_title:
            by_title[norm_title] = existing_idx
        logger.debug("Deduped event id=%s into id=%s", loser.id, merged.id)

    return survivors


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _pick_winner(
    a: IntelligenceEvent, b: IntelligenceEvent
) -> tuple[IntelligenceEvent, IntelligenceEvent]:
    if b.completeness_score() > a.completeness_score():
        return b, a
    return a, b


def _merge_enrichment(winner: IntelligenceEvent, loser: IntelligenceEvent) -> IntelligenceEvent:
    """Return a copy of ``winner`` with entities/tags/topics merged from ``loser``."""
    merged_entities = list(dict.fromkeys([*winner.entities, *loser.entities]))
    merged_tags = list(dict.fromkeys([*winner.tags, *loser.tags]))
    merged_topics = list(dict.fromkeys([*winner.topics, *loser.topics]))
    return winner.model_copy(
        update={
            "entities": merged_entities,
            "tags": merged_tags,
            "topics": merged_topics,
            "summary": winner.summary or loser.summary,
            "url": winner.url or loser.url,
            "published_at": winner.published_at or loser.published_at,
            "event_date": winner.event_date or loser.event_date,
        }
    )


def _canonical_url(url: str | None) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    cleaned_query = "&".join(
        pair for pair in parts.query.split("&") if pair and not _is_tracking_param(pair)
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, cleaned_query, ""))


def _is_tracking_param(pair: str) -> bool:
    key = pair.split("=", 1)[0].lower()
    return any(key.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)


def _normalize_title(title: str) -> str:
    lowered = title.lower()
    stripped = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()
