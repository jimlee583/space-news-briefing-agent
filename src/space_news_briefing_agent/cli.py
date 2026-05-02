"""Command-line entry point.

Examples:
    space-news-briefing                       # full pipeline (default)
    space-news-briefing --skip-email          # write deck, don't email
    space-news-briefing --date 2026-05-01     # override briefing date
    space-news-briefing --topics other.yaml   # use a different topic file
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from .config import load_config
from .logging_setup import configure_logging
from .pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="space-news-briefing",
        description="Generate and email a daily space & defense-space news briefing.",
    )
    parser.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="Override the briefing date (default: today, UTC).",
    )
    parser.add_argument(
        "--topics",
        type=Path,
        default=None,
        help="Path to a topics.yaml file (default: $TOPICS_FILE or ./topics.yaml).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for the generated .pptx (default: $OUTPUT_DIR or ./output).",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="Generate the deck but don't send the email.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override $LOG_LEVEL.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_arg_parser().parse_args(argv)

    cfg = load_config()
    if args.topics is not None:
        cfg = _replace_path(cfg, topics_file=args.topics)
    if args.output_dir is not None:
        cfg = _replace_path(cfg, output_dir=args.output_dir)

    log_level = args.log_level or cfg.log_level
    configure_logging(log_level)

    try:
        result = run_pipeline(cfg, briefing_date=args.date, skip_email=args.skip_email)
    except Exception as exc:  # noqa: BLE001 - top-level handler
        logger.exception("Pipeline failed: %s", exc)
        return 1

    print(f"Deck written to: {result.deck_path}")
    if result.emailed:
        print("Email sent.")
    elif result.email_error:
        print(f"Email NOT sent: {result.email_error}", file=sys.stderr)
    return 0


def _replace_path(
    cfg, *, topics_file: Path | None = None, output_dir: Path | None = None
):  # type: ignore[no-untyped-def]
    """Return a copy of cfg with selected Path fields overridden."""
    from dataclasses import replace

    return replace(
        cfg,
        topics_file=topics_file or cfg.topics_file,
        output_dir=output_dir or cfg.output_dir,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
