"""
web/pdf_generator.py

Generates a formatted academic-style PDF from a draft paper dict
using reportlab's Platypus layout engine.
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
import re


def _clean(text: str) -> str:
    """Escape XML special chars for ReportLab Paragraph."""
    if not text:
        return ""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Remove any remaining control chars
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
    return text


def build_styles() -> dict:
    base = getSampleStyleSheet()

    styles = {
        "journal_title": ParagraphStyle(
            "journal_title",
            fontName="Times-Roman",
            fontSize=8,
            textColor=colors.HexColor("#888888"),
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "paper_title": ParagraphStyle(
            "paper_title",
            fontName="Times-Bold",
            fontSize=16,
            leading=20,
            alignment=TA_CENTER,
            spaceAfter=8,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "authors": ParagraphStyle(
            "authors",
            fontName="Times-Italic",
            fontSize=10,
            alignment=TA_CENTER,
            spaceAfter=4,
            textColor=colors.HexColor("#444444"),
        ),
        "section_heading": ParagraphStyle(
            "section_heading",
            fontName="Times-Bold",
            fontSize=11,
            spaceBefore=14,
            spaceAfter=4,
            textColor=colors.HexColor("#1a1a1a"),
            allCaps=True,
            letterSpacing=0.8,
        ),
        "abstract_box": ParagraphStyle(
            "abstract_box",
            fontName="Times-Roman",
            fontSize=9,
            leading=13,
            alignment=TA_JUSTIFY,
            leftIndent=24,
            rightIndent=24,
            spaceAfter=4,
            textColor=colors.HexColor("#333333"),
        ),
        "abstract_label": ParagraphStyle(
            "abstract_label",
            fontName="Times-Bold",
            fontSize=9,
            leftIndent=24,
            spaceBefore=8,
            spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body",
            fontName="Times-Roman",
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
            textColor=colors.HexColor("#1a1a1a"),
        ),
        "reference": ParagraphStyle(
            "reference",
            fontName="Times-Roman",
            fontSize=8.5,
            leading=12,
            leftIndent=18,
            firstLineIndent=-18,
            spaceAfter=3,
            textColor=colors.HexColor("#333333"),
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName="Times-Italic",
            fontSize=7.5,
            textColor=colors.HexColor("#aaaaaa"),
            alignment=TA_CENTER,
        ),
        "score_label": ParagraphStyle(
            "score_label",
            fontName="Helvetica-Bold",
            fontSize=8,
            textColor=colors.HexColor("#666666"),
            spaceAfter=1,
        ),
        "score_value": ParagraphStyle(
            "score_value",
            fontName="Helvetica",
            fontSize=8,
            textColor=colors.HexColor("#333333"),
            spaceAfter=6,
        ),
    }
    return styles


def generate_pdf(draft: dict, output_path: str) -> str:
    """
    Takes a draft paper dict and writes a formatted PDF to output_path.
    Returns output_path.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=1.1 * inch,
        rightMargin=1.1 * inch,
        topMargin=1.0 * inch,
        bottomMargin=1.0 * inch,
    )

    styles = build_styles()
    story = []

    # ── Journal header ────────────────────────────────────────────────────────
    story.append(Paragraph("ANNALS OF IMPROBABLE RESEARCH", styles["journal_title"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 10))

    # ── Title ─────────────────────────────────────────────────────────────────
    title = _clean(draft.get("title", "Untitled Study"))
    story.append(Paragraph(title, styles["paper_title"]))

    # ── Authors ───────────────────────────────────────────────────────────────
    authors = draft.get("authors", ["Anonymous"])
    story.append(Paragraph(_clean(", ".join(authors)), styles["authors"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#dddddd")))

    # ── Abstract ──────────────────────────────────────────────────────────────
    story.append(Paragraph("ABSTRACT", styles["abstract_label"]))
    abstract_text = _clean(draft.get("abstract", ""))
    story.append(Paragraph(abstract_text, styles["abstract_box"]))
    story.append(Spacer(1, 4))
    story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#dddddd")))

    # ── Body sections ─────────────────────────────────────────────────────────
    sections = [
        ("Introduction", draft.get("introduction", "")),
        ("Methods",      draft.get("methods", "")),
        ("Results",      draft.get("results", "")),
        ("Discussion",   draft.get("discussion", "")),
    ]

    for heading, content in sections:
        story.append(Paragraph(heading, styles["section_heading"]))
        for para in content.split("\n\n"):
            para = para.strip()
            if para:
                story.append(Paragraph(_clean(para), styles["body"]))

    # ── References ────────────────────────────────────────────────────────────
    refs = draft.get("references", [])
    if refs:
        story.append(Paragraph("References", styles["section_heading"]))
        for i, ref in enumerate(refs, 1):
            story.append(Paragraph(f"{i}. {_clean(ref)}", styles["reference"]))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.3, color=colors.HexColor("#dddddd")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Generated by the Ig Nobel Research Agent · For entertainment and scientific inspiration only",
        styles["footer"]
    ))

    doc.build(story)
    return output_path
