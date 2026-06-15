"""Self-contained PDF parser — vision-describe via the local gemma-4 vLLM.

A minimal extraction of the vendored ``parsers/`` PDF path, with the ``core.*`` host-app
dependencies replaced by local shims (``state``, ``vision``). PDF-only.

Public API
----------
    parse_pdf(path, abbrev="ETC") -> list[SourcePage]
        Strategy-routed: text-strategy PDFs use free pymupdf text; scan/diagram PDFs go
        through vision describe. The default entry point.
    describe_pdf(path, abbrev="ETC", *, max_pages=None) -> (list[SourcePage], DescribeMetrics)
        Always vision-describe every page (gemma multimodal). Use directly to force vision.
    parse_pdf_text(path, abbrev="ETC") -> list[SourcePage]
        pymupdf + pdfplumber only, no LLM (free, deterministic).
    detect_pdf_strategy(path) -> PdfStrategyResult
        text / scan / diagram classification.

Endpoint via env (shared with src/stella_kb/llm.py):
    STELLA_LLM_URL    default http://123.37.5.219:8001/v1
    STELLA_LLM_MODEL  default gemma-4-31B-it
"""
from __future__ import annotations

from pathlib import Path

from .describe import DescribeMetrics, describe_pdf
from .router import PdfStrategyResult, detect_pdf_strategy
from .state import SourceAbbrev, SourcePage
from .tables import PdfTablePayload, write_pdf_tables_sidecar
from .text import parse_pdf as parse_pdf_text

__all__ = [
    "parse_pdf", "describe_pdf", "parse_pdf_text", "detect_pdf_strategy",
    "SourcePage", "SourceAbbrev", "PdfStrategyResult", "PdfTablePayload",
    "DescribeMetrics", "write_pdf_tables_sidecar",
]


def parse_pdf(path: Path | str, abbrev: SourceAbbrev = "ETC") -> list[SourcePage]:
    """Strategy-routed parse: text → free pymupdf; scan/diagram → gemma vision describe."""
    path = Path(path)
    strategy = detect_pdf_strategy(path).strategy
    if strategy == "text":
        return parse_pdf_text(path, abbrev)
    pages, _ = describe_pdf(path, abbrev)
    return pages
