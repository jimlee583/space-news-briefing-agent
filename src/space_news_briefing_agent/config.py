"""Runtime configuration loaded from environment variables.

All secrets and tunables are read here. Never hard-code credentials.
Call `load_dotenv()` once at process start (the CLI does this).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_str(name: str, default: str | None = None) -> str | None:
    val = os.environ.get(name)
    if val is None or val.strip() == "":
        return default
    return val.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name!r} must be an integer, got {raw!r}") from exc


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = _env_str(name)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_str(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class LLMConfig:
    api_key: str | None
    model: str

    @property
    def is_configured(self) -> bool:
        # Catch the obvious "still has the placeholder from .env.example" case
        # so callers can fail fast with a clear message instead of an opaque
        # OpenAI 401.
        if not self.api_key:
            return False
        if self.api_key.strip() in {"sk-...", "sk-replace-me", "your-api-key-here"}:
            return False
        return True


@dataclass(frozen=True)
class NewsConfig:
    provider: str
    api_key: str | None
    lookback_hours: int
    max_articles_per_topic: int


@dataclass(frozen=True)
class LaunchConfig:
    """Configuration for the upcoming-launches source.

    ``api_base_url`` is intentionally optional: when ``None`` the source falls
    back to its default (The Space Devs Launch Library 2). Operators can pin a
    private mirror or a paid plan via the env var.
    """

    api_base_url: str | None
    lookahead_days: int
    include_all: bool


@dataclass(frozen=True)
class SourcesConfig:
    """Feature flags controlling which intelligence sources run."""

    enable_news: bool
    enable_launch: bool


@dataclass(frozen=True)
class EmailConfig:
    smtp_host: str
    smtp_port: int
    username: str | None
    password: str | None
    sender: str | None
    recipients: list[str] = field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        return bool(self.username and self.password and self.recipients)


@dataclass(frozen=True)
class AppConfig:
    output_dir: Path
    topics_file: Path
    events_store_path: Path
    log_level: str
    llm: LLMConfig
    news: NewsConfig
    launch: LaunchConfig
    sources: SourcesConfig
    email: EmailConfig


def load_config() -> AppConfig:
    """Read all configuration from environment variables.

    Defaults are chosen to match `.env.example`. Missing secrets are returned as
    `None` rather than raising, so callers (CLI / pipeline) can fail with a
    clear, contextual error message.
    """
    output_dir = Path(_env_str("OUTPUT_DIR", "output") or "output").expanduser()
    topics_file = Path(_env_str("TOPICS_FILE", "topics.yaml") or "topics.yaml").expanduser()
    events_store_path = Path(
        _env_str("EVENTS_STORE_PATH", "output/events.jsonl") or "output/events.jsonl"
    ).expanduser()

    llm = LLMConfig(
        api_key=_env_str("OPENAI_API_KEY"),
        model=_env_str("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
    )

    news = NewsConfig(
        provider=(_env_str("NEWS_PROVIDER", "newsapi") or "newsapi").lower(),
        api_key=_env_str("NEWS_API_KEY"),
        lookback_hours=_env_int("LOOKBACK_HOURS", 36),
        max_articles_per_topic=_env_int("MAX_ARTICLES_PER_TOPIC", 8),
    )

    launch = LaunchConfig(
        api_base_url=_env_str("LAUNCH_API_BASE_URL"),
        lookahead_days=_env_int("LAUNCH_LOOKAHEAD_DAYS", 30),
        include_all=_env_bool("INCLUDE_ALL_LAUNCHES", False),
    )

    sources = SourcesConfig(
        enable_news=_env_bool("ENABLE_NEWS_SOURCE", True),
        enable_launch=_env_bool("ENABLE_LAUNCH_SOURCE", True),
    )

    email_cfg = EmailConfig(
        smtp_host=_env_str("SMTP_HOST", "smtp.gmail.com") or "smtp.gmail.com",
        smtp_port=_env_int("SMTP_PORT", 587),
        username=_env_str("SMTP_USERNAME"),
        password=_env_str("SMTP_PASSWORD"),
        sender=_env_str("EMAIL_FROM") or _env_str("SMTP_USERNAME"),
        recipients=_env_list("EMAIL_TO"),
    )

    return AppConfig(
        output_dir=output_dir,
        topics_file=topics_file,
        events_store_path=events_store_path,
        log_level=(_env_str("LOG_LEVEL", "INFO") or "INFO").upper(),
        llm=llm,
        news=news,
        launch=launch,
        sources=sources,
        email=email_cfg,
    )
