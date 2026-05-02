"""Load tracked topics from a YAML file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class Topic(BaseModel):
    """A tracked company / subject area."""

    name: str = Field(..., min_length=1)
    queries: list[str] = Field(..., min_length=1)
    enabled: bool = True
    max_articles: int | None = Field(default=None, ge=1)

    @field_validator("queries")
    @classmethod
    def _strip_queries(cls, value: list[str]) -> list[str]:
        cleaned = [q.strip() for q in value if q and q.strip()]
        if not cleaned:
            raise ValueError("Topic must have at least one non-empty query.")
        return cleaned


class TopicsConfigError(RuntimeError):
    """Raised when the topics file is missing or malformed."""


def load_topics(path: Path) -> list[Topic]:
    """Load and validate topics from `path`.

    Returns only `enabled` topics in declared order. Raises
    `TopicsConfigError` for missing files or invalid structure so the CLI can
    surface a clear failure.
    """
    if not path.exists():
        raise TopicsConfigError(
            f"Topics file not found: {path}. Create one (see topics.yaml in repo root)."
        )

    try:
        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TopicsConfigError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(raw, dict) or "topics" not in raw:
        raise TopicsConfigError(
            f"{path} must be a mapping with a top-level 'topics:' list."
        )

    items = raw.get("topics") or []
    if not isinstance(items, list):
        raise TopicsConfigError(f"'topics' in {path} must be a list, got {type(items).__name__}.")

    parsed: list[Topic] = []
    for idx, item in enumerate(items):
        try:
            topic = Topic.model_validate(item)
        except Exception as exc:
            raise TopicsConfigError(f"Invalid topic at index {idx} in {path}: {exc}") from exc
        parsed.append(topic)

    enabled = [t for t in parsed if t.enabled]
    skipped = [t.name for t in parsed if not t.enabled]
    if skipped:
        logger.info("Skipping disabled topics: %s", ", ".join(skipped))

    if not enabled:
        raise TopicsConfigError(f"No enabled topics found in {path}.")

    logger.info("Loaded %d enabled topic(s): %s", len(enabled), ", ".join(t.name for t in enabled))
    return enabled
