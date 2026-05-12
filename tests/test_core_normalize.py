from __future__ import annotations

from datetime import UTC, datetime

from space_news_briefing_agent.core.models import (
    IntelligenceEvent,
    LaunchEvent,
    NewsArticleEvent,
)
from space_news_briefing_agent.core.normalize import (
    extract_entities_and_tags,
    normalize_launch_items,
    normalize_news_articles,
)


def test_extract_entities_and_tags_finds_keywords() -> None:
    entities, tags = extract_entities_and_tags(
        "Rocket Lab launches new satellite for Space Force",
        "K2 Space and Lockheed Martin announce constellation deal",
    )
    assert "Rocket Lab" in entities
    assert "Space Force" in entities
    assert "K2 Space" in entities
    assert "Lockheed Martin" in entities
    assert "launch" in tags
    assert "satellite" in tags
    assert "constellation" in tags


def test_extract_entities_is_case_insensitive_and_whole_token() -> None:
    entities, _ = extract_entities_and_tags("nasa awards SDA contract")
    assert "NASA" in entities
    assert "SDA" in entities


def test_extract_entities_does_not_match_substring() -> None:
    # "FCC" should not match "FCCC" (would be wrong word boundary).
    entities, _ = extract_entities_and_tags("FCCC committee meeting")
    assert "FCC" not in entities


def test_normalize_news_articles_produces_news_event() -> None:
    raw = [
        {
            "topic_name": "Rocket Lab",
            "query": "Rocket Lab",
            "title": "Rocket Lab books new SDA contract",
            "source": "SpaceNews",
            "author": "Jane Reporter",
            "url": "https://example.com/rl-sda",
            "published_at": "2026-05-01T12:00:00+00:00",
            "description": "Award details.",
            "content": "Body content.",
        }
    ]
    events = normalize_news_articles(raw)
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, NewsArticleEvent)
    assert event.source_type == "news"
    assert event.url == "https://example.com/rl-sda"
    assert event.published_at == datetime(2026, 5, 1, 12, tzinfo=UTC)
    assert "Rocket Lab" in event.entities
    assert "SDA" in event.entities
    assert "Rocket Lab" in event.topics
    assert event.author == "Jane Reporter"
    assert event.id.startswith("news:")


def test_normalize_news_articles_skips_titleless_rows() -> None:
    events = normalize_news_articles([{"title": "", "url": "https://x.test/a"}])
    assert events == []


def test_normalize_launch_items_extracts_ll2_shape() -> None:
    raw = [
        {
            "id": "ll2-12345",
            "name": "Electron | NROL-XYZ",
            "net": "2026-06-10T14:00:00Z",
            "last_updated": "2026-05-08T10:00:00Z",
            "status": {"name": "Go for Launch"},
            "launch_service_provider": {"name": "Rocket Lab"},
            "rocket": {"configuration": {"name": "Electron"}},
            "mission": {"name": "NROL-XYZ", "description": "Classified payload."},
            "pad": {"name": "LC-1B", "location": {"name": "Mahia, NZ"}},
            "url": "https://example.com/ll2/12345",
        }
    ]
    events = normalize_launch_items(raw)
    assert len(events) == 1
    e = events[0]
    assert isinstance(e, LaunchEvent)
    assert e.source_type == "launch"
    assert e.title == "Electron | NROL-XYZ"
    assert e.event_date == datetime(2026, 6, 10, 14, tzinfo=UTC)
    assert e.launch_provider == "Rocket Lab"
    assert e.vehicle == "Electron"
    assert e.payload == "NROL-XYZ"
    assert e.launch_site == "LC-1B, Mahia, NZ"
    assert e.mission_status == "Go for Launch"
    assert "Rocket Lab" in e.entities
    assert "launch" in e.tags
    assert e.id.startswith("launch:")


def test_normalize_launch_items_handles_missing_fields() -> None:
    events = normalize_launch_items([{"name": "Mystery Launch"}])
    assert len(events) == 1
    assert events[0].event_date is None
    assert events[0].launch_provider is None
    assert "launch" in events[0].tags


def test_intelligence_event_completeness_score_prefers_richer() -> None:
    sparse = IntelligenceEvent(
        id="x",
        source_type="news",
        source_name="s",
        title="t",
    )
    rich = IntelligenceEvent(
        id="y",
        source_type="news",
        source_name="s",
        title="t",
        summary="long summary " * 10,
        url="https://example.com",
        published_at=datetime(2026, 5, 1, tzinfo=UTC),
        entities=["Rocket Lab", "SDA"],
        tags=["launch"],
    )
    assert rich.completeness_score() > sparse.completeness_score()
