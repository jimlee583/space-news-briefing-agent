"""News provider abstraction and built-in implementations."""

from __future__ import annotations

from .base import NewsProvider, NewsProviderError
from .collector import collect_articles
from .registry import build_provider

__all__ = [
    "NewsProvider",
    "NewsProviderError",
    "build_provider",
    "collect_articles",
]
