from __future__ import annotations

from datetime import datetime

from space_news_briefing_agent.core.dedupe import dedupe_events
from space_news_briefing_agent.core.models import (
    IntelligenceEvent,
    NewsArticleEvent,
)


def _news(
    *,
    id_: str,
    title: str,
    url: str | None,
    summary: str | None = None,
    entities: list[str] | None = None,
    tags: list[str] | None = None,
    published_at: datetime | None = None,
) -> NewsArticleEvent:
    return NewsArticleEvent(
        id=id_,
        source_name="test",
        title=title,
        url=url,
        summary=summary,
        entities=entities or [],
        tags=tags or [],
        published_at=published_at,
    )


def test_dedupe_collapses_url_duplicates_and_preserves_completeness() -> None:
    a = _news(id_="a", title="Headline A", url="https://example.com/a?utm_source=x")
    b = _news(
        id_="b",
        title="Headline A duplicate",
        url="https://example.com/a/",
        summary="Has a summary",
        entities=["Rocket Lab"],
    )
    out = dedupe_events([a, b])
    assert len(out) == 1
    assert out[0].summary == "Has a summary"
    assert "Rocket Lab" in out[0].entities


def test_dedupe_collapses_title_duplicates() -> None:
    a = _news(id_="a", title="Same Story Today", url="https://a.test/1")
    b = _news(id_="b", title="Same Story Today", url="https://b.test/2")
    out = dedupe_events([a, b])
    assert len(out) == 1


def test_dedupe_keeps_unrelated_events() -> None:
    a = _news(id_="a", title="A", url="https://a.test")
    b = _news(id_="b", title="B", url="https://b.test")
    out = dedupe_events([a, b])
    assert len(out) == 2


def test_dedupe_merges_entities_from_loser() -> None:
    a = _news(
        id_="a",
        title="Headline A",
        url="https://x.test/a",
        summary="long summary " * 5,
        entities=["Rocket Lab"],
        tags=["launch"],
    )
    b = _news(
        id_="b",
        title="Headline A",
        url="https://x.test/a",
        entities=["SDA"],
        tags=["satellite"],
    )
    out = dedupe_events([a, b])
    assert len(out) == 1
    assert set(out[0].entities) == {"Rocket Lab", "SDA"}
    assert set(out[0].tags) == {"launch", "satellite"}


def test_dedupe_returns_input_order_for_unique_events() -> None:
    events: list[IntelligenceEvent] = [
        _news(id_=str(i), title=f"T{i}", url=f"https://x.test/{i}") for i in range(3)
    ]
    out = dedupe_events(events)
    assert [e.id for e in out] == ["0", "1", "2"]
