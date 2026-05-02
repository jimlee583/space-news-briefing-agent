"""Centralized logging configuration."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    """Configure root logger with a single stderr handler.

    Idempotent: calling this multiple times will not duplicate handlers.
    """
    root = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(numeric_level)

    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        for handler in root.handlers:
            handler.setLevel(numeric_level)
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setLevel(numeric_level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root.addHandler(handler)

    # Quiet down some chatty third-party libs by default.
    logging.getLogger("urllib3").setLevel(max(numeric_level, logging.INFO))
    logging.getLogger("openai").setLevel(max(numeric_level, logging.INFO))
    logging.getLogger("httpx").setLevel(max(numeric_level, logging.WARNING))
