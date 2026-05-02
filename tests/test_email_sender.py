from __future__ import annotations

from pathlib import Path

import pytest

from space_news_briefing_agent.config import EmailConfig
from space_news_briefing_agent.email_sender import EmailError, send_briefing_email
from space_news_briefing_agent.models import Briefing


def _briefing() -> Briefing:
    return Briefing(
        deck_title="Daily Space & Defense-Space News Briefing",
        briefing_date="2026-05-01",
        cross_company_summary="Test summary.",
    )


def test_send_briefing_email_requires_configuration(tmp_path: Path) -> None:
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"fake")

    cfg = EmailConfig(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username=None,
        password=None,
        sender=None,
        recipients=[],
    )

    with pytest.raises(EmailError):
        send_briefing_email(cfg=cfg, briefing=_briefing(), deck_path=deck)


def test_send_briefing_email_requires_existing_deck(tmp_path: Path) -> None:
    cfg = EmailConfig(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="u",
        password="p",
        sender="u@example.com",
        recipients=["to@example.com"],
    )
    with pytest.raises(EmailError):
        send_briefing_email(
            cfg=cfg, briefing=_briefing(), deck_path=tmp_path / "missing.pptx"
        )
