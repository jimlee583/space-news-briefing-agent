"""Tests for ``sources.launches``.

These tests stay offline: we drive the LL2 provider through a stub session
and verify that the relevance filter and resilience behavior work as
documented.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

from space_news_briefing_agent.config import LaunchConfig, load_config
from space_news_briefing_agent.core.models import LaunchEvent
from space_news_briefing_agent.sources.launches import (
    LaunchLibrary2Provider,
    fetch_launch_events,
)


@pytest.fixture
def app_cfg(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("NEWS_API_KEY", "x")
    return load_config()


def _ll2_payload(extra: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    base = [
        {
            "id": "rocket-lab-1",
            "name": "Electron | Mission Alpha",
            "net": "2026-06-01T12:00:00Z",
            "status": {"name": "Go for Launch"},
            "launch_service_provider": {"name": "Rocket Lab"},
            "rocket": {"configuration": {"name": "Electron"}},
            "mission": {"name": "Mission Alpha"},
            "pad": {"name": "LC-1A", "location": {"name": "Mahia, NZ"}},
        },
        {
            "id": "spacex-tracked",
            "name": "Falcon 9 | USSF-Y",
            "net": "2026-06-05T00:00:00Z",
            "launch_service_provider": {"name": "SpaceX"},
            "rocket": {"configuration": {"name": "Falcon 9"}},
            "mission": {"name": "USSF-Y", "description": "Customer: Space Force."},
            "pad": {"name": "SLC-40", "location": {"name": "Cape Canaveral SFS"}},
        },
        {
            "id": "irrelevant",
            "name": "Iran Sat | Simorgh",
            "net": "2026-06-10T00:00:00Z",
            "launch_service_provider": {"name": "Iran Space Agency"},
            "rocket": {"configuration": {"name": "Simorgh"}},
            "mission": {"name": "Iran Sat"},
            "pad": {"name": "Imam Khomeini", "location": {"name": "Iran"}},
        },
    ]
    if extra:
        base.extend(extra)
    return {"results": base}


class _StubSession:
    def __init__(self, payload: dict[str, Any] | None = None, status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.calls: list[Any] = []

    def get(self, url: str, **kwargs: Any) -> Any:  # noqa: ANN401 - test stub
        self.calls.append({"url": url, **kwargs})
        return _StubResponse(self._payload or {}, self._status)


class _StubResponse:
    def __init__(self, payload: dict[str, Any], status: int) -> None:
        self._payload = payload
        self.status_code = status
        self.text = "stub"

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._payload


def test_filter_keeps_tracked_entities_only(app_cfg: Any) -> None:
    session = _StubSession(payload=_ll2_payload())

    with patch(
        "space_news_briefing_agent.sources.launches._build_provider",
        return_value=LaunchLibrary2Provider(session=session),  # type: ignore[arg-type]
    ):
        events = fetch_launch_events(app_cfg)

    titles = {e.title for e in events}
    assert "Electron | Mission Alpha" in titles
    assert "Falcon 9 | USSF-Y" in titles
    assert all("Iran Sat" not in t for t in titles)


def test_include_all_launches_keeps_everything(app_cfg: Any) -> None:
    cfg = replace(
        app_cfg,
        launch=LaunchConfig(api_base_url=None, lookahead_days=30, include_all=True),
    )
    session = _StubSession(payload=_ll2_payload())

    with patch(
        "space_news_briefing_agent.sources.launches._build_provider",
        return_value=LaunchLibrary2Provider(session=session),  # type: ignore[arg-type]
    ):
        events = fetch_launch_events(cfg)

    assert len(events) == 3


def test_provider_failure_falls_back_to_mock(app_cfg: Any) -> None:
    session = _StubSession(payload={}, status=503)

    with patch(
        "space_news_briefing_agent.sources.launches._build_provider",
        return_value=LaunchLibrary2Provider(session=session),  # type: ignore[arg-type]
    ):
        events = fetch_launch_events(app_cfg)

    # Mock entries reference Rocket Lab + SpaceX/Space Force, so the filter
    # keeps them.
    assert len(events) >= 1
    assert all(isinstance(e, LaunchEvent) for e in events)


def test_ll2_provider_calls_upcoming_endpoint() -> None:
    session = _StubSession(payload={"results": []})
    provider = LaunchLibrary2Provider(
        base_url="https://example.test/2.2.0",
        session=session,  # type: ignore[arg-type]
    )

    out = provider.fetch_upcoming(lookahead_days=7)
    assert out == []
    assert session.calls
    call = session.calls[0]
    assert call["url"] == "https://example.test/2.2.0/launch/upcoming/"
    assert "window_end__lte" in call["params"]
    # Window end should be roughly today + 7 days
    parsed = datetime.fromisoformat(call["params"]["window_end__lte"])
    assert parsed > datetime.now(UTC)
