"""Aggregate per-topic queries into a single deduplicated article list."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

from ..models import Article
from ..topics import Topic
from .base import NewsProvider, NewsProviderError

logger = logging.getLogger(__name__)

_TITLE_SIMILARITY_THRESHOLD = 0.88
_TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "mkt_", "icid", "ito")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def collect_articles(
    *,
    provider: NewsProvider,
    topics: list[Topic],
    lookback_hours: int,
    default_max_articles: int,
) -> dict[str, list[Article]]:
    """Run every query for every enabled topic and dedupe results.

    Returns a mapping of `topic_name -> list[Article]`. Topics that yielded
    zero articles are still present in the mapping (with an empty list) so the
    pipeline can decide whether to render an empty section.
    """
    since = datetime.now(UTC) - timedelta(hours=lookback_hours)
    logger.info(
        "Collecting articles from provider=%s since=%s for %d topic(s)",
        provider.name,
        since.isoformat(),
        len(topics),
    )

    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    results: dict[str, list[Article]] = {}

    for topic in topics:
        cap = topic.max_articles or default_max_articles
        topic_articles: list[Article] = []

        for query in topic.queries:
            try:
                raw = provider.search(query, since=since, max_results=cap)
            except NewsProviderError as exc:
                logger.error("Provider failed for topic=%r query=%r: %s", topic.name, query, exc)
                continue

            for article in raw:
                article.topic_name = topic.name
                if not _accept(article, seen_urls, seen_titles):
                    continue
                topic_articles.append(article)
                if len(topic_articles) >= cap:
                    break
            if len(topic_articles) >= cap:
                break

        topic_articles.sort(
            key=lambda a: a.published_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        results[topic.name] = topic_articles
        logger.info(
            "Topic %-28s -> %d article(s) after dedup (cap=%d)",
            topic.name,
            len(topic_articles),
            cap,
        )

    total = sum(len(v) for v in results.values())
    logger.info("Collected %d unique article(s) across %d topic(s)", total, len(results))
    return results


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _accept(article: Article, seen_urls: set[str], seen_titles: list[str]) -> bool:
    canonical = _canonical_url(article.url)
    if not canonical:
        return False
    if canonical in seen_urls:
        return False

    norm_title = _normalize_title(article.title)
    if not norm_title:
        return False
    if _is_similar_to_seen(norm_title, seen_titles):
        return False

    seen_urls.add(canonical)
    seen_titles.append(norm_title)
    return True


def _canonical_url(url: str) -> str:
    """Strip tracking params, fragments, and trailing slashes to dedupe URLs."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""

    query_pairs: Iterable[str] = (
        pair for pair in parts.query.split("&") if pair and not _is_tracking_param(pair)
    )
    cleaned_query = "&".join(query_pairs)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, cleaned_query, ""))


def _is_tracking_param(pair: str) -> bool:
    key = pair.split("=", 1)[0].lower()
    return any(key.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)


def _normalize_title(title: str) -> str:
    lowered = title.lower()
    stripped = re.sub(r"[^a-z0-9 ]+", " ", lowered)
    return re.sub(r"\s+", " ", stripped).strip()


def _is_similar_to_seen(candidate: str, seen: list[str]) -> bool:
    for existing in seen:
        if abs(len(existing) - len(candidate)) > max(len(existing), len(candidate)) * 0.5:
            continue
        if SequenceMatcher(a=candidate, b=existing).ratio() >= _TITLE_SIMILARITY_THRESHOLD:
            return True
    return False
