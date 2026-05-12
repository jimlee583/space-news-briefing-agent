"""Source ingestion modules.

Each source exposes a single ``fetch_*_events(config) -> list[IntelligenceEvent]``
entry point. Adding a new source is a 3-step recipe:

1. Add ``fetch_<source>_events(cfg)`` in a new module here.
2. Wire it into :mod:`space_news_briefing_agent.main` behind a feature flag.
3. (Optional) Add provider-specific config in
   :mod:`space_news_briefing_agent.config`.

Source modules MUST NOT crash the daily pipeline on their own failures —
they should log and return ``[]``.
"""

from __future__ import annotations

from .launches import fetch_launch_events
from .news import fetch_news_events

__all__ = ["fetch_launch_events", "fetch_news_events"]
