from __future__ import annotations

from pathlib import Path

import pytest

from space_news_briefing_agent.topics import TopicsConfigError, load_topics


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "topics.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_topics_happy_path(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
topics:
  - name: K2 Space
    queries:
      - '"K2 Space"'
      - '"K2 satellites"'
  - name: Disabled Co
    enabled: false
    queries:
      - 'Disabled Co'
  - name: Capped Co
    queries:
      - 'Capped Co'
    max_articles: 3
""",
    )
    topics = load_topics(path)
    assert [t.name for t in topics] == ["K2 Space", "Capped Co"]
    assert topics[1].max_articles == 3


def test_load_topics_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TopicsConfigError):
        load_topics(tmp_path / "nope.yaml")


def test_load_topics_requires_queries(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
topics:
  - name: Bad Co
    queries: []
""",
    )
    with pytest.raises(TopicsConfigError):
        load_topics(path)


def test_load_topics_all_disabled_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
topics:
  - name: Off
    enabled: false
    queries: ['x']
""",
    )
    with pytest.raises(TopicsConfigError):
        load_topics(path)
