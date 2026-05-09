"""NewsAPI.org implementation of `NewsProvider`."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import Article
from .base import NewsProviderError

logger = logging.getLogger(__name__)

_ENDPOINT = "https://newsapi.org/v2/everything"
_TIMEOUT_SECONDS = 20

# Defaults for transient-failure retries. `total=3` means up to four total
# attempts (the original + three retries) with exponential backoff:
#   attempt 2 after ~0.5s, attempt 3 after ~1.0s, attempt 4 after ~2.0s.
# We retry on connection errors (DNS hiccups, TCP/TLS resets) and on the
# server-side 5xx codes that typically clear up on their own. We deliberately
# do NOT retry on 401 (auth — hard fail) or 429 (rate limit — surfaces with a
# dedicated message; blindly hammering would be rude).
_DEFAULT_RETRY_TOTAL = 3
_DEFAULT_BACKOFF_FACTOR = 0.5
_RETRY_STATUS_FORCELIST = (500, 502, 503, 504)


def _build_default_session(
    *,
    retry_total: int,
    backoff_factor: float,
) -> requests.Session:
    """Return a `requests.Session` with retry/backoff mounted on https://."""
    retry = Retry(
        total=retry_total,
        connect=retry_total,
        read=retry_total,
        status=retry_total,
        backoff_factor=backoff_factor,
        status_forcelist=_RETRY_STATUS_FORCELIST,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class NewsAPIProvider:
    """Thin wrapper around the NewsAPI `/v2/everything` endpoint."""

    name = "newsapi"

    def __init__(
        self,
        api_key: str,
        *,
        language: str = "en",
        sort_by: str = "publishedAt",
        session: requests.Session | None = None,
        retry_total: int = _DEFAULT_RETRY_TOTAL,
        backoff_factor: float = _DEFAULT_BACKOFF_FACTOR,
    ) -> None:
        if not api_key:
            raise NewsProviderError("NEWS_API_KEY is required for the NewsAPI provider.")
        self._api_key = api_key
        self._language = language
        self._sort_by = sort_by
        self._session = session or _build_default_session(
            retry_total=retry_total,
            backoff_factor=backoff_factor,
        )

    def search(
        self,
        query: str,
        *,
        since: datetime,
        max_results: int,
    ) -> list[Article]:
        params: dict[str, str | int] = {
            "q": query,
            "from": since.replace(microsecond=0).isoformat(),
            "language": self._language,
            "sortBy": self._sort_by,
            "pageSize": max(1, min(max_results, 100)),
        }
        headers = {"X-Api-Key": self._api_key, "User-Agent": "space-news-briefing-agent/0.1"}

        try:
            response = self._session.get(
                _ENDPOINT, params=params, headers=headers, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            raise NewsProviderError(f"NewsAPI request failed for query {query!r}: {exc}") from exc

        if response.status_code == 401:
            raise NewsProviderError("NewsAPI rejected the API key (401). Check NEWS_API_KEY.")
        if response.status_code == 429:
            raise NewsProviderError("NewsAPI rate limit hit (429). Try later or upgrade plan.")
        if not response.ok:
            raise NewsProviderError(
                f"NewsAPI returned HTTP {response.status_code} for query {query!r}: "
                f"{response.text[:300]}"
            )

        payload: dict[str, Any] = response.json()
        if payload.get("status") != "ok":
            raise NewsProviderError(
                f"NewsAPI error for query {query!r}: {payload.get('code')} - {payload.get('message')}"
            )

        raw_articles: list[dict[str, Any]] = payload.get("articles") or []
        articles: list[Article] = []
        for raw in raw_articles[:max_results]:
            article = self._to_article(raw, query=query)
            if article is not None:
                articles.append(article)

        logger.debug("NewsAPI returned %d article(s) for query %r", len(articles), query)
        return articles

    @staticmethod
    def _to_article(raw: dict[str, Any], *, query: str) -> Article | None:
        url = (raw.get("url") or "").strip()
        title = (raw.get("title") or "").strip()
        if not url or not title or title == "[Removed]":
            return None

        source = ""
        src = raw.get("source")
        if isinstance(src, dict):
            source = (src.get("name") or "").strip()

        published_at: datetime | None = None
        published_raw = raw.get("publishedAt")
        if isinstance(published_raw, str) and published_raw:
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except ValueError:
                published_at = None

        return Article(
            topic_name="",  # filled in by the collector
            query=query,
            title=title,
            source=source,
            author=(raw.get("author") or "").strip(),
            url=url,
            published_at=published_at,
            description=(raw.get("description") or "").strip(),
            content=(raw.get("content") or "").strip(),
        )
