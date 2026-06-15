"""SourcePage — the one shared data type the PDF parser emits.

A minimal local stand-in for the vendored ``core.schema.state`` (which assumed a much
larger host app). One PDF page = one SourcePage; ``page`` is the 1-based PDF page number,
``text`` is the page's structured markdown. The optional fields exist only so this type
stays drop-in compatible with the vendored parsers if more of them are ported later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# The vendored code typed this as a Literal enum of deal abbreviations (IM/CDD/…). For a
# PDF-only extraction it carries no logic, so it's just a short source tag string.
SourceAbbrev = str


@dataclass
class SourcePage:
    """One page of a parsed document."""

    abbrev: SourceAbbrev
    file: Path
    page: int
    text: str
    word_page_start: int | None = None
    word_page_end: int | None = None
    section_path: list[str] = field(default_factory=list)
