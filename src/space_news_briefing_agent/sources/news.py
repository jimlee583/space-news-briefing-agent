"""News-source adapter.

Wraps the existing NewsAPI provider + collector and emits normalized
``IntelligenceEvent`` objects so downstream code only sees core types.

Existing behavior preserved:
* same env vars (NEWS_API_KEY, NEWS_PROVIDER, LOOKBACK_HOURS, …)
* same topics.yaml format
* same per-topic dedup / cap logic
"""

from __future__ import annotations

import logging

from ..config import AppConfig
from ..core.models import IntelligenceEvent
from ..core.normalize import normalize_news_articles
from ..news import build_provider, collect_articles
from ..news.base import NewsProviderError
from ..topics import TopicsConfigError, load_topics

logger = logging.getLogger(__name__)


def fetch_news_events(cfg: AppConfig) -> list[IntelligenceEvent]:
    """Collect news articles for every enabled topic and normalize them.

    Returns an empty list (and logs a warning) on any non-fatal provider
    error so the rest of the pipeline can keep going.
    """
    try:
        topics = load_topics(cfg.topics_file)
    except TopicsConfigError as exc:
        logger.error("News source: failed to load topics — %s", exc)
        return []

    try:
        provider = build_provider(cfg.news)
    except NewsProviderError as exc:
        logger.error("News source: failed to build provider — %s", exc)
        return []

    articles_by_topic = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=cfg.news.lookback_hours,
        default_max_articles=cfg.news.max_articles_per_topic,
    )

    events: list[IntelligenceEvent] = []
    for topic_name, articles in articles_by_topic.items():
        as_dicts = [{**a.model_dump(mode="python"), "topic_name": topic_name} for a in articles]
        events.extend(normalize_news_articles(as_dicts, source_name=provider.name or "news"))

    logger.info("News source produced %d normalized event(s)", len(events))
    return events
