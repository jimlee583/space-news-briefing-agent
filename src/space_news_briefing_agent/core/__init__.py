"""Core data layer for the space intelligence pipeline.

These modules are intentionally source-agnostic. Anything that ingests data
(news, launches, FCC filings, SAM.gov solicitations, …) normalizes its
records into the Pydantic types declared in :mod:`.models`, runs them through
:mod:`.dedupe`, and may persist them via :mod:`.storage`.

Higher-level code (summarizer, deck, emailer) only ever depends on
``IntelligenceEvent`` (or a typed subclass) — never on a specific source's
wire format. That is what makes new sources easy to add later.
"""

from __future__ import annotations

from .dedupe import dedupe_events
from .models import (
    BriefingInput,
    IntelligenceEvent,
    LaunchEvent,
    NewsArticleEvent,
)
from .normalize import (
    extract_entities_and_tags,
    normalize_launch_items,
    normalize_news_articles,
)
from .storage import append_events, load_events, save_events

__all__ = [
    "BriefingInput",
    "IntelligenceEvent",
    "LaunchEvent",
    "NewsArticleEvent",
    "append_events",
    "dedupe_events",
    "extract_entities_and_tags",
    "load_events",
    "normalize_launch_items",
    "normalize_news_articles",
    "save_events",
]
