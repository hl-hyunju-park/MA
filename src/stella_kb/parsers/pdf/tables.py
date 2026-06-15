"""Describe markdown → 표 payload 분리.

vision describe 가 생성한 markdown 표를 추출해:
- text 청크 = description + 검색용 markdown 표 + row-level 검색 행
- payload sidecar = headers/rows/labels 구조화 JSON  (인용 join 키: abbrev, page, table_idx)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

_MAX_HEADER_PREVIEW = 3
_MAX_HEADER_CHARS = 40

# markdown 표 패턴: 헤더 행 + 구분 행(|---|) + 1개 이상의 데이터 행
_TABLE_PATTERN = re.compile(
    r"(\|[^\n]+\|\n)"        # 헤더 행
    r"(\|[-:| ]+\|\n)"       # 구분 행
    r"((?:\|[^\n]+\|\n)+)",  # 데이터 행
)


@dataclass
class PdfTablePayload:
    """표 1개 = payload 1개. 값은 여기에만, RAG 텍스트에는 description 만."""

    abbrev: str
    file: str
    page: int                       # 1-based PDF 페이지 번호
    table_idx: int                  # 문서 전체 기준 1-based 순서
    caption: str | None = None
    headers: list[str] = field(default_factory=list)
    row_labels: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    col_count: int = 0
    row_count: int = 0


def _parse_md_row(row_line: str) -> list[str]:
    row_line = row_line.strip()
    if row_line.startswith("|"):
        row_line = row_line[1:]
    if row_line.endswith("|"):
        row_line = row_line[:-1]
    return [cell.strip() for cell in row_line.split("|")]


def _truncate(s: str, limit: int = _MAX_HEADER_CHARS) -> str:
    return s if len(s) <= limit else s[:limit - 1] + "…"


def _compose_description(*, table_idx: int, headers: list[str], col_count: int,
                        row_count: int) -> str:
    preview = [_truncate(h) for h in headers[:_MAX_HEADER_PREVIEW] if h]
    preview_str = ", ".join(preview) if preview else ""
    suffix = "..." if len(headers) > _MAX_HEADER_PREVIEW else ""
    header_part = f"헤더={preview_str}{suffix}" if preview_str else f"{col_count}열"
    return f"[표 {table_idx}: {col_count}열 × {row_count}행, {header_part}]"


def _render_table_markdown(*, headers: list[str], rows: list[list[str]]) -> str:
    if not headers:
        return ""
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        cells = list(r) + [""] * max(0, len(headers) - len(r))
        cells = cells[: len(headers)]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _render_row_search_text(*, headers: list[str], rows: list[list[str]]) -> str:
    """row-level 검색 친화 문자열 — `라벨 / 컬럼 = 값` 1행씩."""
    if not headers or len(headers) < 2 or not rows:
        return ""
    out: list[str] = []
    for r in rows:
        if not r:
            continue
        label = (r[0] or "").strip()
        if not label:
            continue
        for ci in range(1, len(headers)):
            if ci >= len(r):
                break
            val = (r[ci] or "").strip()
            if not val:
                continue
            col = (headers[ci] or f"col{ci}").strip() or f"col{ci}"
            out.append(f"{label} / {col} = {val}")
    return "\n".join(out)


def extract_tables_from_markdown(
    markdown: str, *, page: int, table_offset: int = 0,
) -> tuple[str, list[PdfTablePayload]]:
    """markdown 의 표를 추출하고 표 자리를 description+검색행으로 교체.

    Returns ``(cleaned_markdown, payloads)`` — 전역 table_idx = table_offset + 로컬순서.
    """
    payloads: list[PdfTablePayload] = []
    local_idx = 0

    def _replace(match: re.Match) -> str:
        nonlocal local_idx
        local_idx += 1
        global_idx = table_offset + local_idx
        headers = _parse_md_row(match.group(1))
        col_count = len(headers)
        data_rows = [_parse_md_row(line) for line in match.group(3).splitlines() if line.strip()]
        row_count = len(data_rows)
        row_labels = [r[0] if r else "" for r in data_rows]
        payloads.append(PdfTablePayload(
            abbrev="", file="", page=page, table_idx=global_idx, caption=None,
            headers=headers, row_labels=row_labels, rows=data_rows,
            col_count=col_count, row_count=row_count,
        ))
        descr = _compose_description(table_idx=global_idx, headers=headers,
                                     col_count=col_count, row_count=row_count)
        table_md = _render_table_markdown(headers=headers, rows=data_rows)
        row_text = _render_row_search_text(headers=headers, rows=data_rows)
        parts = [descr, table_md] + ([row_text] if row_text else [])
        return "\n".join(p for p in parts if p) + "\n"

    cleaned = _TABLE_PATTERN.sub(_replace, markdown)
    return cleaned, payloads


def write_pdf_tables_sidecar(
    payloads: list[PdfTablePayload], out_dir: Path, *, source_file: str, abbrev: str,
) -> dict | None:
    """payload 리스트 → ``tables.jsonl`` + ``tables_manifest.json``. 빈 입력 시 None."""
    if not payloads:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "tables.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as fp:
        for p in payloads:
            fp.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    manifest = {
        "source_file": source_file,
        "source_abbrev": abbrev,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "table_count": len(payloads),
        "tables_jsonl": jsonl_path.name,
    }
    (out_dir / "tables_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
