"""Source-specific normalization into ``IntelligenceEvent`` types.

Each ``normalize_*`` helper is intentionally tolerant of partial / messy input:
sources will eventually disagree about field names, and we'd rather emit a
slightly thinner event than crash the daily run.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .models import IntelligenceEvent, LaunchEvent, NewsArticleEvent

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Entity / tag extraction
# --------------------------------------------------------------------------- #

# Phrase -> bucket. Order matters only for deterministic output: we emit
# matches in the order declared here. Matching is case-insensitive and
# whole-word-ish (so "satellite" doesn't match "satellites" only by accident
# of the regex below — see the boundary handling).
_ENTITY_KEYWORDS: list[tuple[str, str]] = [
    ("K2 Space", "entity"),
    ("Boeing", "entity"),
    ("Lockheed Martin", "entity"),
    ("York Space", "entity"),
    ("Rocket Lab", "entity"),
    ("Northrop Grumman", "entity"),
    ("Space Force", "entity"),
    ("SDA", "entity"),
    ("NASA", "entity"),
    ("FCC", "entity"),
]

_TAG_KEYWORDS: list[str] = [
    "launch",
    "satellite",
    "constellation",
    "spacecraft",
    "optical comm",
    "missile warning",
]


def _compile_pattern(phrase: str, *, allow_suffix: bool = False) -> re.Pattern[str]:
    """Build a case-insensitive whole-token-ish matcher for ``phrase``.

    We allow internal whitespace to match any run of whitespace so "Lockheed
    Martin" still matches "Lockheed  Martin". When ``allow_suffix`` is true
    the trailing word-boundary is relaxed so "launch" also matches
    "launches"/"launching" — useful for content tags.
    """
    parts = [re.escape(tok) for tok in phrase.split()]
    body = r"\s+".join(parts)
    trailing = "" if allow_suffix else r"(?![A-Za-z0-9])"
    return re.compile(rf"(?<![A-Za-z0-9]){body}{trailing}", re.IGNORECASE)


_ENTITY_PATTERNS = [(_compile_pattern(p), p) for p, _ in _ENTITY_KEYWORDS]
_TAG_PATTERNS = [(_compile_pattern(p, allow_suffix=True), p) for p in _TAG_KEYWORDS]


def extract_entities_and_tags(*texts: str | None) -> tuple[list[str], list[str]]:
    """Return ``(entities, tags)`` discovered in any of ``texts``.

    Lists are de-duplicated and stable-ordered (declaration order).
    """
    haystack = " ".join(t for t in texts if t)
    entities: list[str] = []
    tags: list[str] = []

    for pattern, label in _ENTITY_PATTERNS:
        if pattern.search(haystack) and label not in entities:
            entities.append(label)

    for pattern, label in _TAG_PATTERNS:
        if pattern.search(haystack) and label not in tags:
            tags.append(label)

    return entities, tags


# --------------------------------------------------------------------------- #
# News articles
# --------------------------------------------------------------------------- #


def normalize_news_articles(
    articles: Iterable[dict[str, Any]],
    *,
    source_name: str = "NewsAPI",
) -> list[IntelligenceEvent]:
    """Normalize already-collected news article dicts into ``NewsArticleEvent``.

    Accepts the dict shape produced by :class:`Article.model_dump` so the
    existing news collector keeps working unchanged.
    """
    events: list[IntelligenceEvent] = []
    for raw in articles:
        url = (raw.get("url") or "").strip() or None
        title = (raw.get("title") or "").strip()
        if not title:
            continue

        description = (raw.get("description") or "").strip()
        content = (raw.get("content") or "").strip()
        summary = description or content or None

        published_at = _coerce_datetime(raw.get("published_at"))

        topic_name = (raw.get("topic_name") or "").strip()
        topics = [topic_name] if topic_name else []

        entities, tags = extract_entities_and_tags(title, description, content, topic_name)

        event_id = _stable_id(url or title, prefix="news")

        events.append(
            NewsArticleEvent(
                id=event_id,
                source_name=(raw.get("source") or source_name).strip() or source_name,
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                event_date=None,
                entities=entities,
                topics=topics,
                tags=tags,
                raw=dict(raw),
                author=(raw.get("author") or None) or None,
            )
        )
    return events


# --------------------------------------------------------------------------- #
# Launches
# --------------------------------------------------------------------------- #


def normalize_launch_items(
    items: Iterable[dict[str, Any]],
    *,
    source_name: str = "Launch Library 2",
) -> list[IntelligenceEvent]:
    """Normalize launch schedule dicts into ``LaunchEvent``.

    The expected shape loosely follows The Space Devs Launch Library 2 (LL2)
    format but is forgiving — any provider that returns dicts with sensible
    keys (name / net / rocket / mission / pad) will work.
    """
    events: list[IntelligenceEvent] = []
    for raw in items:
        title = _extract_launch_title(raw)
        if not title:
            continue

        url = _first_str(raw, ["url", "info_url", "info_urls"])
        # ``net`` is the LL2 "no earlier than" timestamp; that's our T-0.
        event_date = _coerce_datetime(raw.get("net") or raw.get("event_date"))
        published_at = _coerce_datetime(
            raw.get("last_updated") or raw.get("updated") or raw.get("published_at")
        )

        rocket = raw.get("rocket") or {}
        config = rocket.get("configuration") if isinstance(rocket, dict) else None
        vehicle = ((config or {}).get("name") if isinstance(config, dict) else None) or _first_str(
            raw, ["vehicle", "rocket_name"]
        )

        provider = _extract_launch_provider(raw)
        payload = _extract_payload(raw)
        site = _extract_launch_site(raw)
        status = _extract_status(raw)

        summary = _first_str(raw, ["mission_description", "description", "summary"])
        if summary is None:
            mission = raw.get("mission")
            if isinstance(mission, dict):
                summary = (mission.get("description") or "").strip() or None

        entities, tags = extract_entities_and_tags(title, summary, provider, vehicle, payload, site)
        # A launch is unambiguously a launch; ensure the tag is present.
        if "launch" not in tags:
            tags.append("launch")

        event_id = _stable_id(
            _first_str(raw, ["id", "slug"]) or url or f"{title}|{event_date or ''}",
            prefix="launch",
        )

        events.append(
            LaunchEvent(
                id=event_id,
                source_name=source_name,
                title=title,
                summary=summary,
                url=url,
                published_at=published_at,
                event_date=event_date,
                entities=entities,
                topics=[],
                tags=tags,
                raw=dict(raw),
                launch_provider=provider,
                vehicle=vehicle,
                payload=payload,
                launch_site=site,
                mission_status=status,
            )
        )
    return events


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _stable_id(seed: str, *, prefix: str) -> str:
    digest = hashlib.sha1(seed.strip().encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _first_str(raw: dict[str, Any], keys: list[str]) -> str | None:
    for k in keys:
        v = raw.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _extract_launch_title(raw: dict[str, Any]) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    mission = raw.get("mission")
    if isinstance(mission, dict):
        m_name = mission.get("name")
        if isinstance(m_name, str) and m_name.strip():
            return m_name.strip()
    return _first_str(raw, ["title"]) or ""


def _extract_launch_provider(raw: dict[str, Any]) -> str | None:
    lsp = raw.get("launch_service_provider")
    if isinstance(lsp, dict):
        name = lsp.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(lsp, str) and lsp.strip():
        return lsp.strip()
    return _first_str(raw, ["provider", "launch_provider"])


def _extract_payload(raw: dict[str, Any]) -> str | None:
    mission = raw.get("mission")
    if isinstance(mission, dict):
        name = mission.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return _first_str(raw, ["payload", "payloads"])


def _extract_launch_site(raw: dict[str, Any]) -> str | None:
    pad = raw.get("pad")
    if isinstance(pad, dict):
        name = pad.get("name")
        location = pad.get("location")
        loc_name = location.get("name") if isinstance(location, dict) else None
        bits = [b for b in (name, loc_name) if isinstance(b, str) and b.strip()]
        if bits:
            return ", ".join(bits)
    return _first_str(raw, ["launch_site", "site", "location"])


def _extract_status(raw: dict[str, Any]) -> str | None:
    status = raw.get("status")
    if isinstance(status, dict):
        name = status.get("name") or status.get("abbrev")
        if isinstance(name, str) and name.strip():
            return name.strip()
    if isinstance(status, str) and status.strip():
        return status.strip()
    return _first_str(raw, ["mission_status"])
