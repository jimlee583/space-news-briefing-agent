from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from space_news_briefing_agent.core.models import (
    IntelligenceEvent,
    LaunchEvent,
    NewsArticleEvent,
)
from space_news_briefing_agent.core.storage import (
    append_events,
    load_events,
    save_events,
)


def _news() -> NewsArticleEvent:
    return NewsArticleEvent(
        id="news:a",
        source_name="t",
        title="Headline",
        url="https://example.com/a",
        published_at=datetime(2026, 5, 1, tzinfo=UTC),
        entities=["Rocket Lab"],
        author="Jane",
    )


def _launch() -> LaunchEvent:
    return LaunchEvent(
        id="launch:b",
        source_name="ll2",
        title="Electron | Mission",
        event_date=datetime(2026, 5, 5, 12, tzinfo=UTC),
        launch_provider="Rocket Lab",
        vehicle="Electron",
        tags=["launch"],
    )


def test_load_events_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_events(tmp_path / "nope.jsonl") == []


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    events: list[IntelligenceEvent] = [_news(), _launch()]
    save_events(path, events)

    loaded = load_events(path)
    assert len(loaded) == 2
    by_id = {e.id: e for e in loaded}
    assert isinstance(by_id["news:a"], NewsArticleEvent)
    assert isinstance(by_id["launch:b"], LaunchEvent)
    assert by_id["news:a"].published_at == datetime(2026, 5, 1, tzinfo=UTC)
    assert by_id["launch:b"].launch_provider == "Rocket Lab"


def test_append_events_creates_file_and_extends(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    append_events(path, [_news()])
    append_events(path, [_launch()])

    loaded = load_events(path)
    assert [e.id for e in loaded] == ["news:a", "launch:b"]


def test_save_overwrites(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    save_events(path, [_news()])
    save_events(path, [_launch()])
    loaded = load_events(path)
    assert [e.id for e in loaded] == ["launch:b"]


def test_load_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    save_events(path, [_news()])
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n")  # blank line
        fh.write("not-json\n")
    loaded = load_events(path)
    assert len(loaded) == 1
