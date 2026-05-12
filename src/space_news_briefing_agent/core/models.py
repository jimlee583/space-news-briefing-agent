"""Core Pydantic models for the space intelligence pipeline.

Every source (news, launches, future FCC/SAM.gov/etc.) normalizes its records
into one of the ``IntelligenceEvent`` subclasses defined here. Downstream
consumers (summarizer, deck) only depend on these types.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Use a discriminated-union-friendly literal so future source types are easy
# to add without breaking existing serialized data.
SourceType = Literal["news", "launch"]


class IntelligenceEvent(BaseModel):
    """A normalized signal from any space-intelligence source.

    Subclasses (NewsArticleEvent, LaunchEvent, …) add source-specific fields
    while preserving this common shape so the summarizer and deck can iterate
    over a heterogeneous list uniformly.
    """

    # ``extra="allow"`` keeps round-trips lossless when newer schemas land —
    # we don't want to silently drop fields just because an older deployment
    # is reading a newer JSONL store.
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Stable identifier; usually URL or provider ID hash.")
    source_type: SourceType
    source_name: str = Field(..., description="Human-readable provider, e.g. 'NewsAPI'.")
    title: str
    summary: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    event_date: datetime | None = Field(
        default=None,
        description="When the event itself occurs (e.g. launch T-0). For news this is usually None.",
    )
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Original provider payload, kept for debugging / reprocessing.",
    )

    def completeness_score(self) -> int:
        """Rough heuristic used by dedupe to keep the most complete duplicate."""
        score = 0
        if self.summary:
            score += len(self.summary)
        if self.url:
            score += 50
        if self.published_at is not None:
            score += 20
        if self.event_date is not None:
            score += 20
        score += 10 * len(self.entities)
        score += 5 * len(self.tags)
        score += 5 * len(self.topics)
        return score


class NewsArticleEvent(IntelligenceEvent):
    """News article normalized into the common event shape."""

    source_type: Literal["news"] = "news"
    author: str | None = None


class LaunchEvent(IntelligenceEvent):
    """Scheduled launch normalized into the common event shape.

    ``event_date`` carries the launch T-0; ``published_at`` carries the time
    the schedule entry was last updated by the provider.
    """

    source_type: Literal["launch"] = "launch"
    launch_provider: str | None = None
    vehicle: str | None = None
    payload: str | None = None
    launch_site: str | None = None
    mission_status: str | None = None


class BriefingInput(BaseModel):
    """Input bundle the summarizer consumes."""

    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    events: list[IntelligenceEvent] = Field(default_factory=list)

    def by_source_type(self, source_type: SourceType) -> list[IntelligenceEvent]:
        return [e for e in self.events if e.source_type == source_type]
