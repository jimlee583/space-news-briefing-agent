"""Construct a `NewsProvider` from configuration.

Add a new provider by writing a small factory function and registering it in
`_FACTORIES`.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import NewsConfig
from .base import NewsProvider, NewsProviderError
from .newsapi import NewsAPIProvider


def _build_newsapi(cfg: NewsConfig) -> NewsProvider:
    if not cfg.api_key:
        raise NewsProviderError("NEWS_API_KEY is required for the NewsAPI provider.")
    return NewsAPIProvider(api_key=cfg.api_key)


_FACTORIES: dict[str, Callable[[NewsConfig], NewsProvider]] = {
    "newsapi": _build_newsapi,
}


def build_provider(cfg: NewsConfig) -> NewsProvider:
    """Return a configured `NewsProvider` for `cfg.provider`."""
    factory = _FACTORIES.get(cfg.provider)
    if factory is None:
        supported = ", ".join(sorted(_FACTORIES))
        raise NewsProviderError(
            f"Unknown news provider {cfg.provider!r}. Supported: {supported}."
        )
    return factory(cfg)
