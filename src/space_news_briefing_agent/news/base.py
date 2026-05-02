"""News provider interface.

Implementations should be small, stateless, and only translate between the
provider's wire format and our `Article` model. Adding a new provider (SerpAPI,
Bing, Google CSE, RSS, etc.) means:

1. Implement a class with a `search(query, since, max_results) -> list[Article]`
   method.
2. Register it in `news/registry.py`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..models import Article


class NewsProviderError(RuntimeError):
    """Raised on unrecoverable provider failures (auth, quota, network)."""


class NewsProvider(Protocol):
    """Minimal contract every news provider must satisfy."""

    name: str

    def search(
        self,
        query: str,
        *,
        since: datetime,
        max_results: int,
    ) -> list[Article]:
        """Return up to `max_results` articles matching `query` newer than `since`.

        Implementations must:
          * leave `topic_name` blank (the collector fills it in),
          * set `query` to the exact string used,
          * always return a list (possibly empty) — never `None`,
          * raise `NewsProviderError` on auth/quota/network failures.
        """
        ...
