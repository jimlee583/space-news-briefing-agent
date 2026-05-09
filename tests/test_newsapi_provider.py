"""Tests for `space_news_briefing_agent.news.newsapi.NewsAPIProvider`.

We don't drive real network retries here (that would be flaky and slow);
instead we verify:

* the provider mounts an `HTTPAdapter` with the expected `urllib3.Retry` config,
* a successful response is parsed into `Article`s,
* a `requests.RequestException` raised by the session bubbles up as
  `NewsProviderError`,
* application-level error responses (401, 429, non-OK JSON) map to
  `NewsProviderError` without further retries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from space_news_briefing_agent.news.base import NewsProviderError
from space_news_briefing_agent.news.newsapi import NewsAPIProvider

SINCE = datetime(2026, 5, 7, 12, tzinfo=UTC)


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"status": "ok", "articles": []}
        self.text = "fake response body"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeSession:
    """Minimal stand-in for `requests.Session` for unit tests."""

    def __init__(
        self, *, response: _FakeResponse | None = None, exc: Exception | None = None
    ) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _as_session(fake: _FakeSession) -> requests.Session:
    """Quiet mypy: the provider only ever calls `.get()` on the session."""
    return cast(requests.Session, fake)


def test_default_session_has_retry_adapter_with_expected_config() -> None:
    provider = NewsAPIProvider(api_key="k")

    adapter = provider._session.get_adapter("https://newsapi.org/")
    assert isinstance(adapter, HTTPAdapter)

    retry = adapter.max_retries
    assert isinstance(retry, Retry)
    assert retry.total == 3
    assert retry.connect == 3
    assert retry.read == 3
    assert retry.status == 3
    assert retry.backoff_factor == 0.5
    assert set(retry.status_forcelist or []) == {500, 502, 503, 504}
    assert retry.allowed_methods == frozenset({"GET"})
    assert retry.respect_retry_after_header is True


def test_retry_total_and_backoff_are_configurable() -> None:
    provider = NewsAPIProvider(api_key="k", retry_total=5, backoff_factor=1.25)

    adapter = provider._session.get_adapter("https://newsapi.org/")
    assert isinstance(adapter, HTTPAdapter)
    retry = adapter.max_retries
    assert isinstance(retry, Retry)
    assert retry.total == 5
    assert retry.backoff_factor == 1.25


def test_search_parses_successful_response() -> None:
    payload = {
        "status": "ok",
        "articles": [
            {
                "url": "https://example.com/a",
                "title": "Headline A",
                "source": {"name": "Example Times"},
                "author": "Jane Reporter",
                "publishedAt": "2026-05-08T12:00:00Z",
                "description": "Lead.",
                "content": "Body.",
            },
            {
                "url": "",  # filtered: missing url
                "title": "No URL",
            },
            {
                "url": "https://example.com/c",
                "title": "[Removed]",  # filtered: removed sentinel
            },
        ],
    }
    session = _FakeSession(response=_FakeResponse(payload=payload))
    provider = NewsAPIProvider(api_key="k", session=_as_session(session))

    out = provider.search("rocket lab", since=SINCE, max_results=10)

    assert len(out) == 1
    assert out[0].url == "https://example.com/a"
    assert out[0].source == "Example Times"
    assert out[0].query == "rocket lab"
    assert out[0].published_at == datetime(2026, 5, 8, 12, tzinfo=UTC)

    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://newsapi.org/v2/everything"
    assert call["params"]["q"] == "rocket lab"
    assert call["params"]["pageSize"] == 10
    assert call["headers"]["X-Api-Key"] == "k"


def test_request_exception_is_wrapped_as_provider_error() -> None:
    session = _FakeSession(exc=requests.ConnectionError("boom"))
    provider = NewsAPIProvider(api_key="k", session=_as_session(session))

    with pytest.raises(NewsProviderError) as excinfo:
        provider.search("q", since=SINCE, max_results=5)

    assert "boom" in str(excinfo.value)


def test_401_raises_auth_error_without_retry() -> None:
    session = _FakeSession(response=_FakeResponse(status_code=401))
    provider = NewsAPIProvider(api_key="k", session=_as_session(session))

    with pytest.raises(NewsProviderError, match="401"):
        provider.search("q", since=SINCE, max_results=5)
    assert len(session.calls) == 1


def test_429_raises_rate_limit_error_without_retry() -> None:
    session = _FakeSession(response=_FakeResponse(status_code=429))
    provider = NewsAPIProvider(api_key="k", session=_as_session(session))

    with pytest.raises(NewsProviderError, match="429"):
        provider.search("q", since=SINCE, max_results=5)
    assert len(session.calls) == 1


def test_payload_status_not_ok_raises() -> None:
    session = _FakeSession(
        response=_FakeResponse(payload={"status": "error", "code": "x", "message": "nope"})
    )
    provider = NewsAPIProvider(api_key="k", session=_as_session(session))

    with pytest.raises(NewsProviderError, match="nope"):
        provider.search("q", since=SINCE, max_results=5)


def test_empty_api_key_rejected() -> None:
    with pytest.raises(NewsProviderError):
        NewsAPIProvider(api_key="")
