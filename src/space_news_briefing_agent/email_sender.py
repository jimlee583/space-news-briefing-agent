"""Send the generated deck as an email attachment over SMTP (STARTTLS)."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

from .config import EmailConfig
from .models import Briefing

logger = logging.getLogger(__name__)


class EmailError(RuntimeError):
    """Raised on SMTP / message-construction failure."""


def send_briefing_email(
    *,
    cfg: EmailConfig,
    briefing: Briefing,
    deck_path: Path,
) -> None:
    """Email `deck_path` to `cfg.recipients`.

    Raises `EmailError` if email is not configured or SMTP fails. The pipeline
    catches this and treats it as a non-fatal warning (deck is still on disk).
    """
    if not cfg.is_configured:
        raise EmailError(
            "Email is not configured (need SMTP_USERNAME, SMTP_PASSWORD, EMAIL_TO)."
        )
    if not deck_path.exists():
        raise EmailError(f"Deck file not found at {deck_path}")

    message = _build_message(cfg=cfg, briefing=briefing, deck_path=deck_path)

    logger.info(
        "Sending briefing email via %s:%d to %d recipient(s)",
        cfg.smtp_host,
        cfg.smtp_port,
        len(cfg.recipients),
    )

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            assert cfg.username and cfg.password  # narrowed by is_configured
            smtp.login(cfg.username, cfg.password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"SMTP send failed: {exc}") from exc

    logger.info("Email sent successfully.")


def _build_message(*, cfg: EmailConfig, briefing: Briefing, deck_path: Path) -> EmailMessage:
    subject = f"Daily Space & Defense-Space News Briefing - {briefing.briefing_date}"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg.sender or (cfg.username or "")
    message["To"] = ", ".join(cfg.recipients)

    body_lines = [
        f"Daily Space & Defense-Space News Briefing for {briefing.briefing_date}.",
        "",
        "Executive summary:",
        briefing.cross_company_summary or "(no summary available)",
        "",
        "Tracked topics:",
    ]
    body_lines.extend(f"  - {b.topic_name}" for b in briefing.company_briefs)
    body_lines.extend(
        [
            "",
            "Full deck attached.",
            "",
            "— space-news-briefing-agent",
        ]
    )
    message.set_content("\n".join(body_lines))

    deck_bytes = deck_path.read_bytes()
    message.add_attachment(
        deck_bytes,
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=deck_path.name,
    )
    return message
