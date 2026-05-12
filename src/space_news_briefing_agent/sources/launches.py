"""Upcoming-launch source.

Default implementation hits The Space Devs **Launch Library 2** public
endpoint::

    GET {LAUNCH_API_BASE_URL}/launch/upcoming/?window_end={iso}&mode=detailed

When ``LAUNCH_API_BASE_URL`` is unset or the call fails, we fall back to a
bundled mock so the daily briefing never crashes because of a flaky upstream.
The mock is small, dated, and clearly labeled — it's for resilience, not
substance.

TODO(launch-provider): The Space Devs has both a free tier
(``ll.thespacedevs.com/2.2.0``) and a paid mirror (``lldev.thespacedevs.com``
for dev). Confirm which mirror you want for production load and pin it via
``LAUNCH_API_BASE_URL``. Validate the exact JSON shape before relying on
specific fields beyond what :mod:`..core.normalize` already tolerates.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import requests

from ..config import AppConfig, LaunchConfig
from ..core.models import IntelligenceEvent, LaunchEvent
from ..core.normalize import normalize_launch_items

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Provider abstraction
# --------------------------------------------------------------------------- #


class LaunchProvider(Protocol):
    name: str

    def fetch_upcoming(self, *, lookahead_days: int) -> list[dict[str, Any]]:
        """Return raw launch dicts within the next ``lookahead_days`` days."""
        ...


# --------------------------------------------------------------------------- #
# The Space Devs / Launch Library 2 implementation
# --------------------------------------------------------------------------- #


_DEFAULT_LL2_BASE = "https://ll.thespacedevs.com/2.2.0"
_TIMEOUT_SECONDS = 20
_DEFAULT_PAGE_SIZE = 50


class LaunchLibrary2Provider:
    """Minimal client for The Space Devs Launch Library 2."""

    name = "launch_library_2"

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_LL2_BASE,
        session: requests.Session | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()

    def fetch_upcoming(self, *, lookahead_days: int) -> list[dict[str, Any]]:
        endpoint = f"{self._base}/launch/upcoming/"
        window_end = (datetime.now(UTC) + timedelta(days=lookahead_days)).replace(microsecond=0)
        params: dict[str, str | int] = {
            "limit": _DEFAULT_PAGE_SIZE,
            "mode": "detailed",
            "window_end__lte": window_end.isoformat(),
        }
        headers = {"User-Agent": "space-news-briefing-agent/0.1 (+launches)"}

        logger.debug("LL2 GET %s params=%s", endpoint, params)
        response = self._session.get(
            endpoint, params=params, headers=headers, timeout=_TIMEOUT_SECONDS
        )
        if not response.ok:
            raise RuntimeError(f"LL2 returned HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        results = payload.get("results")
        if not isinstance(results, list):
            raise RuntimeError("LL2 response missing 'results' list")
        return list(results)


# --------------------------------------------------------------------------- #
# Mock fallback
# --------------------------------------------------------------------------- #


def _mock_upcoming_launches(*, lookahead_days: int) -> list[dict[str, Any]]:
    """A tiny, hand-curated sample. Used only when the real provider is down."""
    now = datetime.now(UTC)
    samples: list[dict[str, Any]] = [
        {
            "id": "mock-rl-electron-001",
            "name": "Electron | Confidential Smallsat",
            "net": (now + timedelta(days=2)).isoformat(),
            "last_updated": now.isoformat(),
            "status": {"name": "Go for Launch"},
            "launch_service_provider": {"name": "Rocket Lab"},
            "rocket": {"configuration": {"name": "Electron"}},
            "mission": {
                "name": "Confidential Smallsat",
                "description": "Mock entry; replace with real LL2 results when the API is reachable.",
            },
            "pad": {"name": "LC-1A", "location": {"name": "Mahia, New Zealand"}},
        },
        {
            "id": "mock-spacex-usff-002",
            "name": "Falcon 9 | USSF mission (mock)",
            "net": (now + timedelta(days=10)).isoformat(),
            "last_updated": now.isoformat(),
            "status": {"name": "TBD"},
            "launch_service_provider": {"name": "SpaceX"},
            "rocket": {"configuration": {"name": "Falcon 9 Block 5"}},
            "mission": {
                "name": "USSF Payload (mock)",
                "description": "Mock entry referencing Space Force as customer.",
            },
            "pad": {"name": "SLC-40", "location": {"name": "Cape Canaveral SFS"}},
        },
    ]
    cutoff = now + timedelta(days=lookahead_days)
    return [s for s in samples if datetime.fromisoformat(s["net"]) <= cutoff]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def fetch_launch_events(cfg: AppConfig) -> list[IntelligenceEvent]:
    """Fetch + normalize + filter upcoming launches.

    Designed never to raise to the orchestrator: any error degrades to "no
    launch events for today" plus a warning log.
    """
    launch_cfg = cfg.launch
    provider = _build_provider(launch_cfg)

    try:
        raw_items = provider.fetch_upcoming(lookahead_days=launch_cfg.lookahead_days)
    except (requests.RequestException, RuntimeError) as exc:
        logger.warning(
            "Launch provider %s failed (%s); falling back to mock data.",
            provider.name,
            exc,
        )
        raw_items = _mock_upcoming_launches(lookahead_days=launch_cfg.lookahead_days)
    except Exception as exc:  # noqa: BLE001 - last-line resilience
        logger.warning("Unexpected launch provider error: %s. Returning no launches.", exc)
        return []

    events = normalize_launch_items(raw_items, source_name=provider.name)
    filtered = list(_apply_relevance_filter(events, launch_cfg=launch_cfg))
    logger.info(
        "Launch source produced %d event(s) (raw=%d, after filter=%d, include_all=%s)",
        len(filtered),
        len(raw_items),
        len(filtered),
        launch_cfg.include_all,
    )
    return filtered


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _build_provider(launch_cfg: LaunchConfig) -> LaunchProvider:
    base = launch_cfg.api_base_url or _DEFAULT_LL2_BASE
    return LaunchLibrary2Provider(base_url=base)


# Tracked entities we always want to see launches for, even when
# INCLUDE_ALL_LAUNCHES is false. Lower-cased for case-insensitive matching.
_TRACKED_LAUNCH_KEYWORDS = (
    "rocket lab",
    "spacex",
    "sda",
    "space force",
    "ussf",
    "nasa",
    "lockheed martin",
    "northrop grumman",
    "boeing",
    "york space",
    "k2 space",
)


def _apply_relevance_filter(
    events: Iterable[IntelligenceEvent], *, launch_cfg: LaunchConfig
) -> Iterable[IntelligenceEvent]:
    if launch_cfg.include_all:
        yield from events
        return

    for event in events:
        if not isinstance(event, LaunchEvent):
            yield event
            continue
        haystack = " ".join(
            s.lower()
            for s in (
                event.title,
                event.summary or "",
                event.launch_provider or "",
                event.payload or "",
                event.launch_site or "",
            )
        )
        if any(kw in haystack for kw in _TRACKED_LAUNCH_KEYWORDS):
            yield event
