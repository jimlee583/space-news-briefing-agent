"""Schema-shape regression tests.

OpenAI's structured-output ("strict" JSON-schema) subset rejects several
keywords that pydantic emits by default. The tests in this file lock down the
constraints we've already hit so they can't silently come back.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from space_news_briefing_agent.models import Briefing, NewsItem


def _all_format_values(node: Any) -> list[str]:
    """Recursively collect every JSON-Schema `format: <value>` string in a tree."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "format" and isinstance(value, str):
                found.append(value)
            found.extend(_all_format_values(value))
    elif isinstance(node, list):
        for child in node:
            found.extend(_all_format_values(child))
    return found


def test_briefing_schema_has_no_format_uri() -> None:
    """OpenAI strict structured outputs reject `format: uri` (HTTP 400).

    See: BadRequestError "Invalid schema for response_format 'Briefing':
    In context=('properties', 'url'), 'uri' is not a valid format.".
    """
    schema = Briefing.model_json_schema()
    formats = _all_format_values(schema)
    assert "uri" not in formats, (
        f"Briefing schema must not contain 'format: uri' (got {formats}); "
        "use plain `str` with a validator instead of pydantic.HttpUrl."
    )


def test_news_item_schema_has_no_format_uri() -> None:
    schema = NewsItem.model_json_schema()
    assert "uri" not in _all_format_values(schema)


def test_news_item_url_validator_accepts_http_and_https() -> None:
    NewsItem(
        title="t",
        source="s",
        date="2026-05-01",
        url="https://example.com/a",
        summary="s",
        why_it_matters="w",
        confidence="high",
    )
    NewsItem(
        title="t",
        source="s",
        date="2026-05-01",
        url="http://example.com/a",
        summary="s",
        why_it_matters="w",
        confidence="medium",
    )


@pytest.mark.parametrize("bad_url", ["", "ftp://x.test/y", "example.com", "javascript:alert(1)"])
def test_news_item_url_validator_rejects_non_http(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        NewsItem(
            title="t",
            source="s",
            date="2026-05-01",
            url=bad_url,
            summary="s",
            why_it_matters="w",
            confidence="low",
        )


def test_briefing_source_list_validator_rejects_bad_urls() -> None:
    with pytest.raises(ValidationError):
        Briefing(
            briefing_date="2026-05-01",
            cross_company_summary="x",
            source_list=["not-a-url"],
        )


def test_briefing_schema_is_serializable_json() -> None:
    """Sanity check: the schema we send to OpenAI is JSON-serializable."""
    json.dumps(Briefing.model_json_schema())
