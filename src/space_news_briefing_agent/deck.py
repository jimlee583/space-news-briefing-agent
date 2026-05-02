"""PowerPoint deck generator.

The deck layout is intentionally simple and theme-agnostic so it works with
any default `python-pptx` template. Slides are added in this order:

1. Title slide
2. Cross-company executive summary
3. Industry themes
4. Defense-space implications
5. One summary slide per company
6. One slide per top news item, grouped by company
7. Watch items
8. Sources
"""

from __future__ import annotations

import logging
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt

from .models import Briefing, CompanyBrief, NewsItem

logger = logging.getLogger(__name__)

# Layout indices for the default `python-pptx` template:
#   0: Title Slide, 1: Title and Content, 5: Title Only, 6: Blank
_LAYOUT_TITLE = 0
_LAYOUT_TITLE_AND_CONTENT = 1
_LAYOUT_TITLE_ONLY = 5

_BODY_FONT_SIZE_PT = 16
_BULLET_FONT_SIZE_PT = 14
_FOOTER_FONT_SIZE_PT = 10


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def build_deck(briefing: Briefing, output_dir: Path) -> Path:
    """Render `briefing` to `output_dir/space_defense_news_briefing_YYYY-MM-DD.pptx`.

    Returns the absolute path to the generated file.
    """
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    _add_title_slide(prs, briefing)
    _add_summary_slide(
        prs,
        title="Executive Summary",
        body_paragraphs=[briefing.cross_company_summary]
        if briefing.cross_company_summary
        else ["No summary available."],
    )
    _add_bulleted_slide(prs, "Industry Themes", briefing.industry_themes)
    _add_bulleted_slide(prs, "Defense-Space Implications", briefing.defense_space_implications)

    for brief in briefing.company_briefs:
        _add_company_summary_slide(prs, brief)

    for brief in briefing.company_briefs:
        for item in brief.top_items:
            _add_news_item_slide(prs, brief.topic_name, item)

    _add_bulleted_slide(prs, "Watch Items", briefing.watch_items)
    _add_sources_slide(prs, [str(u) for u in briefing.source_list])

    filename = f"space_defense_news_briefing_{briefing.briefing_date}.pptx"
    output_path = output_dir / filename
    prs.save(output_path)
    logger.info("Wrote deck: %s", output_path)
    return output_path


# --------------------------------------------------------------------------- #
# Slide builders
# --------------------------------------------------------------------------- #


def _add_title_slide(prs: Presentation, briefing: Briefing) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE])
    title = slide.shapes.title
    if title is not None:
        title.text = briefing.deck_title or "Daily Space & Defense-Space News Briefing"
    if len(slide.placeholders) > 1:
        subtitle = slide.placeholders[1]
        subtitle.text = f"Briefing date: {briefing.briefing_date}"


def _add_summary_slide(prs: Presentation, *, title: str, body_paragraphs: list[str]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE_AND_CONTENT])
    _set_title(slide, title)
    body = _content_placeholder(slide)
    if body is None:
        return
    tf = body.text_frame
    tf.word_wrap = True
    tf.clear()
    for idx, paragraph in enumerate(body_paragraphs):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = paragraph
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(_BODY_FONT_SIZE_PT)


def _add_bulleted_slide(prs: Presentation, title: str, bullets: list[str]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE_AND_CONTENT])
    _set_title(slide, title)
    body = _content_placeholder(slide)
    if body is None:
        return
    tf = body.text_frame
    tf.word_wrap = True
    tf.clear()

    items = [b.strip() for b in bullets if b and b.strip()]
    if not items:
        items = ["No items reported."]

    for idx, bullet in enumerate(items):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = bullet
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(_BULLET_FONT_SIZE_PT)


def _add_company_summary_slide(prs: Presentation, brief: CompanyBrief) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE_AND_CONTENT])
    _set_title(slide, f"{brief.topic_name} — Summary")
    body = _content_placeholder(slide)
    if body is None:
        return
    tf = body.text_frame
    tf.word_wrap = True
    tf.clear()

    p = tf.paragraphs[0]
    p.text = brief.executive_summary or "No summary available."
    for run in p.runs:
        run.font.size = Pt(_BODY_FONT_SIZE_PT)

    if brief.implications:
        _add_section_heading(tf, "Implications")
        for line in brief.implications:
            _add_bullet(tf, line, level=1)

    if brief.watch_items:
        _add_section_heading(tf, "Watch")
        for line in brief.watch_items:
            _add_bullet(tf, line, level=1)


def _add_news_item_slide(prs: Presentation, topic_name: str, item: NewsItem) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE_AND_CONTENT])
    _set_title(slide, f"{topic_name} — {_truncate(item.title, 90)}")
    body = _content_placeholder(slide)
    if body is None:
        return
    tf = body.text_frame
    tf.word_wrap = True
    tf.clear()

    meta_bits = [item.source]
    if item.date:
        meta_bits.append(item.date)
    meta_bits.append(f"confidence: {item.confidence}")
    meta = " · ".join(b for b in meta_bits if b)

    p = tf.paragraphs[0]
    p.text = meta
    for run in p.runs:
        run.font.size = Pt(_FOOTER_FONT_SIZE_PT)
        run.font.italic = True

    _add_section_heading(tf, "Summary")
    _add_bullet(tf, item.summary, level=1)

    _add_section_heading(tf, "Why it matters")
    _add_bullet(tf, item.why_it_matters, level=1)

    _add_section_heading(tf, "Source")
    _add_bullet(tf, str(item.url), level=1)


def _add_sources_slide(prs: Presentation, urls: list[str]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[_LAYOUT_TITLE_AND_CONTENT])
    _set_title(slide, "Sources")
    body = _content_placeholder(slide)
    if body is None:
        return
    tf = body.text_frame
    tf.word_wrap = True
    tf.clear()

    if not urls:
        p = tf.paragraphs[0]
        p.text = "No sources cited."
        for run in p.runs:
            run.font.size = Pt(_BULLET_FONT_SIZE_PT)
        return

    for idx, url in enumerate(urls):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.text = url
        p.level = 0
        for run in p.runs:
            run.font.size = Pt(_FOOTER_FONT_SIZE_PT)


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #


def _set_title(slide: object, text: str) -> None:
    title = getattr(slide.shapes, "title", None)  # type: ignore[attr-defined]
    if title is not None:
        title.text = text


def _content_placeholder(slide: object):  # type: ignore[no-untyped-def]
    """Return the first non-title placeholder, or None.

    `python-pptx` exposes placeholders by index; idx 0 is the title and idx 1
    is the body for the standard "Title and Content" layout.
    """
    placeholders = slide.placeholders  # type: ignore[attr-defined]
    for placeholder in placeholders:
        if placeholder.placeholder_format.idx != 0:
            return placeholder
    return None


def _add_section_heading(tf, text: str) -> None:  # type: ignore[no-untyped-def]
    p = tf.add_paragraph()
    p.text = text
    p.level = 0
    for run in p.runs:
        run.font.size = Pt(_BULLET_FONT_SIZE_PT)
        run.font.bold = True


def _add_bullet(tf, text: str, *, level: int) -> None:  # type: ignore[no-untyped-def]
    p = tf.add_paragraph()
    p.text = text
    p.level = level
    for run in p.runs:
        run.font.size = Pt(_BULLET_FONT_SIZE_PT)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


# Silence unused-import warnings for shapes constants kept for future styling hooks.
_ = MSO_SHAPE
