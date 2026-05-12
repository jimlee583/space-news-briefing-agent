"""Lightweight JSONL persistence for ``IntelligenceEvent`` rows.

Why JSONL: it's append-only-friendly, trivially diffable in git, easy to
inspect with ``jq`` / ``rg``, and good enough for the per-day volumes this
agent produces. Swap to SQLite/Parquet later when querying becomes the
bottleneck.

Each line is a single ``IntelligenceEvent`` (or subclass) serialized via
Pydantic with ``mode="json"`` so datetimes round-trip cleanly.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .models import IntelligenceEvent, LaunchEvent, NewsArticleEvent

logger = logging.getLogger(__name__)


# Map ``source_type`` discriminator to the concrete Pydantic class. Update
# this when new event subclasses land.
_TYPE_REGISTRY: dict[str, type[IntelligenceEvent]] = {
    "news": NewsArticleEvent,
    "launch": LaunchEvent,
}


def load_events(path: str | Path) -> list[IntelligenceEvent]:
    """Read events from a JSONL file. Missing files return ``[]``."""
    p = Path(path)
    if not p.exists():
        logger.debug("Events store %s does not exist; returning empty list.", p)
        return []

    events: list[IntelligenceEvent] = []
    with p.open("r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON at %s:%d (%s)", p, lineno, exc)
                continue
            event = _model_from_payload(payload)
            if event is not None:
                events.append(event)
    logger.debug("Loaded %d event(s) from %s", len(events), p)
    return events


def save_events(path: str | Path, events: Iterable[IntelligenceEvent]) -> None:
    """Atomically (best-effort) overwrite ``path`` with ``events`` as JSONL."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(_serialize(event) + "\n")
            count += 1
    tmp.replace(p)
    logger.info("Wrote %d event(s) to %s", count, p)


def append_events(path: str | Path, events: Iterable[IntelligenceEvent]) -> None:
    """Append ``events`` to ``path``, creating the file if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with p.open("a", encoding="utf-8") as fh:
        for event in events:
            fh.write(_serialize(event) + "\n")
            count += 1
    logger.info("Appended %d event(s) to %s", count, p)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _serialize(event: IntelligenceEvent) -> str:
    return event.model_dump_json(exclude_none=False)


def _model_from_payload(payload: dict[str, Any]) -> IntelligenceEvent | None:
    source_type = payload.get("source_type")
    cls = _TYPE_REGISTRY.get(str(source_type), IntelligenceEvent)
    try:
        return cls.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 - malformed rows must not crash the loader
        logger.warning("Skipping unparseable event row: %s", exc)
        return None
