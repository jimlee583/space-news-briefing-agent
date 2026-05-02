from __future__ import annotations

from datetime import UTC, datetime

from space_news_briefing_agent.models import Article
from space_news_briefing_agent.news.collector import collect_articles
from space_news_briefing_agent.topics import Topic


class StubProvider:
    name = "stub"

    def __init__(self, by_query: dict[str, list[Article]]) -> None:
        self._by_query = by_query
        self.calls: list[tuple[str, int]] = []

    def search(
        self, query: str, *, since: datetime, max_results: int
    ) -> list[Article]:
        self.calls.append((query, max_results))
        return list(self._by_query.get(query, []))


def _article(title: str, url: str, query: str = "q") -> Article:
    return Article(
        topic_name="",
        query=query,
        title=title,
        url=url,
        published_at=datetime(2026, 5, 1, 12, tzinfo=UTC),
    )


def test_collector_dedups_by_url() -> None:
    provider = StubProvider(
        {
            "q1": [_article("Headline A", "https://example.com/a?utm_source=x")],
            "q2": [_article("Headline A duplicate", "https://example.com/a/")],
        }
    )
    topics = [Topic(name="T", queries=["q1", "q2"])]

    out = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=24,
        default_max_articles=10,
    )

    assert len(out["T"]) == 1
    assert out["T"][0].topic_name == "T"


def test_collector_dedups_by_similar_title() -> None:
    provider = StubProvider(
        {
            "q1": [_article("Rocket Lab launches mission today", "https://a.test/1")],
            "q2": [_article("Rocket Lab launches mission today!", "https://b.test/2")],
        }
    )
    topics = [Topic(name="T", queries=["q1", "q2"])]

    out = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=24,
        default_max_articles=10,
    )

    assert len(out["T"]) == 1


def test_collector_respects_per_topic_cap() -> None:
    provider = StubProvider(
        {
            "q": [_article(f"Title {i}", f"https://x.test/{i}") for i in range(20)],
        }
    )
    topics = [Topic(name="T", queries=["q"], max_articles=4)]

    out = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=24,
        default_max_articles=10,
    )

    assert len(out["T"]) == 4


def test_collector_produces_entry_for_every_topic() -> None:
    provider = StubProvider({})
    topics = [Topic(name="A", queries=["x"]), Topic(name="B", queries=["y"])]

    out = collect_articles(
        provider=provider,
        topics=topics,
        lookback_hours=24,
        default_max_articles=10,
    )

    assert set(out.keys()) == {"A", "B"}
    assert out["A"] == [] and out["B"] == []
