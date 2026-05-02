"""Pydantic models for the briefing pipeline.

Two model families live here:

* `Article` is the **input** to summarization: a normalized record produced by a
  `NewsProvider`.
* `NewsItem`, `CompanyBrief`, and `Briefing` are the **structured output** the
  LLM is constrained to return. They feed deck generation directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# --------------------------------------------------------------------------- #
# Inputs (news collection)
# --------------------------------------------------------------------------- #


class Article(BaseModel):
    """Normalized news article from any provider."""

    model_config = ConfigDict(extra="ignore")

    topic_name: str
    query: str
    title: str
    source: str = ""
    author: str = ""
    url: str
    published_at: datetime | None = None
    description: str = ""
    content: str = ""

    def short_id(self) -> str:
        """Short stable identifier used in LLM prompts & dedup logs."""
        return f"{self.source or '?'} | {self.title[:80]}"


# --------------------------------------------------------------------------- #
# LLM structured output
# --------------------------------------------------------------------------- #

Confidence = Literal["high", "medium", "low"]


class NewsItem(BaseModel):
    """A single notable story called out in the deck."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., description="Concise, factual headline.")
    source: str = Field(..., description="Publisher name, e.g. 'Reuters'.")
    date: str = Field(
        ..., description="Publication date as ISO-8601 (YYYY-MM-DD) when known, else ''."
    )
    url: HttpUrl
    summary: str = Field(..., description="2-4 sentence neutral summary grounded in the article.")
    why_it_matters: str = Field(
        ..., description="One short paragraph: strategic / commercial / defense relevance."
    )
    confidence: Confidence = Field(
        ...,
        description=(
            "Reporter's confidence the underlying claim is well-supported by the cited source(s)."
        ),
    )


class CompanyBrief(BaseModel):
    """Per-topic (typically per-company) summary block."""

    model_config = ConfigDict(extra="forbid")

    topic_name: str
    executive_summary: str = Field(
        ..., description="3-6 sentences: what changed in the last 24-48 hours for this topic."
    )
    top_items: list[NewsItem] = Field(
        default_factory=list,
        description="Most important stories for this topic, ordered by importance.",
    )
    implications: list[str] = Field(
        default_factory=list,
        description="Bullet points: defense-space, supply chain, competitive positioning.",
    )
    watch_items: list[str] = Field(
        default_factory=list,
        description="Things to monitor over the next few days/weeks.",
    )


class Briefing(BaseModel):
    """Top-level briefing the deck builder consumes."""

    model_config = ConfigDict(extra="forbid")

    deck_title: str = "Daily Space & Defense-Space News Briefing"
    briefing_date: str = Field(..., description="ISO-8601 date, YYYY-MM-DD.")
    cross_company_summary: str = Field(
        ...,
        description=(
            "5-8 sentence executive summary across all tracked companies. "
            "Call out the single most important development if any."
        ),
    )
    company_briefs: list[CompanyBrief] = Field(default_factory=list)
    industry_themes: list[str] = Field(
        default_factory=list,
        description="Bullet points: cross-cutting themes (e.g. SDA awards, launch cadence).",
    )
    defense_space_implications: list[str] = Field(
        default_factory=list,
        description="Bullet points specifically on national-security space implications.",
    )
    watch_items: list[str] = Field(
        default_factory=list,
        description="Cross-company watch list for the coming days.",
    )
    source_list: list[HttpUrl] = Field(
        default_factory=list,
        description="Deduplicated list of every URL cited in the briefing.",
    )
