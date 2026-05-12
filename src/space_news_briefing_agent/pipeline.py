"""Backwards-compatible alias for :mod:`space_news_briefing_agent.main`.

The orchestration logic moved to :mod:`.main` as part of the
event-pipeline refactor; this module is kept so existing callers (notably
:mod:`.cli`, scripts, and tests) keep working without churn.
"""

from __future__ import annotations

from .main import PipelineResult, run_pipeline

__all__ = ["PipelineResult", "run_pipeline"]
