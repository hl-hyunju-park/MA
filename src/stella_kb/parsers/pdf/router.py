"""PDF 전략 라우터 — 텍스트 / 스캔 / 다이어그램 PDF 자동 판정.

샘플 페이지의 layout 신호값 평균을 임계와 비교해 ``text/scan/diagram`` 을 결정한다.
``text`` 는 pymupdf 텍스트 추출(무료)로 충분, ``scan``/``diagram`` 은 vision describe 대상.

판정 단위: doc-level (전체 PDF = 1 strategy). cheap pymupdf 호출만 사용.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import fitz  # pymupdf

PdfStrategy = Literal["text", "scan", "diagram"]

# 샘플링 — 첫 N 페이지 + 마지막 1 페이지. 표지/목차/끝 페이지 형태 보정.
_SAMPLE_FIRST_N = 5
_INCLUDE_LAST = True

# 임계값
_MIN_TEXT_CHARS_PER_PAGE = 100  # 이하면 "텍스트 없음" 으로 판정
_SCAN_TEXT_RATIO_THRESHOLD = 0.10  # 텍스트 있는 페이지 비율 < 10% → scan
_DIAGRAM_IMAGE_AREA_THRESHOLD = 0.40  # 이미지 면적 평균 비율
_DIAGRAM_TEXT_AREA_THRESHOLD = 0.30  # 텍스트 면적 비율 (이 미만일 때만 diagram)
_DIAGRAM_DRAWING_THRESHOLD = 15  # 페이지 평균 drawing count


@dataclass(frozen=True)
class PdfStrategyResult:
    """PDF strategy 판정 + 신호값."""

    strategy: PdfStrategy
    confidence: float           # 0.0~1.0
    reason: str                 # 한국어 1줄 — 어떤 신호로 판정했는지
    signals: dict[str, float]   # text_ratio, avg_image_area_ratio, avg_drawings 등


def _sample_page_indices(total_pages: int) -> list[int]:
    """0-based page index 샘플 목록 반환."""
    if total_pages <= 0:
        return []
    n_first = min(_SAMPLE_FIRST_N, total_pages)
    indices = list(range(n_first))
    if _INCLUDE_LAST and total_pages > n_first:
        indices.append(total_pages - 1)
    return indices


def _page_signals(page: fitz.Page) -> dict[str, float]:
    """페이지 1장의 layout 신호값. cheap pymupdf 호출만."""
    page_rect = page.rect
    page_area = float(page_rect.width * page_rect.height) or 1.0

    text = page.get_text("text").strip()
    text_len = len(text)

    image_area = 0.0
    for img in page.get_images(full=True):
        xref = img[0]
        try:
            for rect in page.get_image_rects(xref):
                image_area += float(rect.width) * float(rect.height)
        except Exception:
            continue

    try:
        drawing_count = len(page.get_drawings())
    except Exception:
        drawing_count = 0

    text_area = 0.0
    try:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            bbox = block["bbox"]
            text_area += (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    except Exception:
        text_area = 0.0

    return {
        "text_len": float(text_len),
        "image_area_ratio": image_area / page_area,
        "text_area_ratio": text_area / page_area,
        "drawing_count": float(drawing_count),
    }


def detect_pdf_strategy(path: Path) -> PdfStrategyResult:
    """PDF strategy 판정 — ``text/scan/diagram`` + confidence + reason + raw signals."""
    doc = fitz.open(str(path))
    try:
        total = doc.page_count
        indices = _sample_page_indices(total)
        if not indices:
            return PdfStrategyResult(
                strategy="text", confidence=0.0,
                reason="페이지 0 — 기본 text 전략 fallback",
                signals={"total_pages": 0.0},
            )

        per_page = [_page_signals(doc[i]) for i in indices]
        n = float(len(per_page))

        text_pages = sum(1 for s in per_page if s["text_len"] >= _MIN_TEXT_CHARS_PER_PAGE)
        text_ratio = text_pages / n
        avg_image_ratio = sum(s["image_area_ratio"] for s in per_page) / n
        avg_text_area_ratio = sum(s["text_area_ratio"] for s in per_page) / n
        avg_drawings = sum(s["drawing_count"] for s in per_page) / n

        signals = {
            "total_pages": float(total),
            "sampled_pages": n,
            "text_ratio": round(text_ratio, 3),
            "avg_image_area_ratio": round(avg_image_ratio, 3),
            "avg_text_area_ratio": round(avg_text_area_ratio, 3),
            "avg_drawings": round(avg_drawings, 1),
        }

        # 분기 — 우선순위: scan > diagram > text
        if text_ratio < _SCAN_TEXT_RATIO_THRESHOLD:
            return PdfStrategyResult(
                strategy="scan", confidence=round(1.0 - text_ratio, 3),
                reason=(f"텍스트 추출 가능 페이지 {text_pages}/{int(n)} "
                        f"(< {_SCAN_TEXT_RATIO_THRESHOLD:.0%}) — 스캔 PDF 후보"),
                signals=signals,
            )

        if (
            avg_image_ratio > _DIAGRAM_IMAGE_AREA_THRESHOLD
            and avg_text_area_ratio < _DIAGRAM_TEXT_AREA_THRESHOLD
        ) or avg_drawings > _DIAGRAM_DRAWING_THRESHOLD:
            conf = max(min(avg_image_ratio / 0.6, 1.0), min(avg_drawings / 30.0, 1.0))
            return PdfStrategyResult(
                strategy="diagram", confidence=round(conf, 3),
                reason=(f"이미지 면적 {avg_image_ratio:.0%}, "
                        f"drawings {avg_drawings:.0f}/페이지 — 차트/다이어그램 후보"),
                signals=signals,
            )

        return PdfStrategyResult(
            strategy="text", confidence=round(text_ratio, 3),
            reason=(f"텍스트 추출 페이지 {text_ratio:.0%}, "
                    f"이미지 면적 {avg_image_ratio:.0%} — 텍스트 PDF"),
            signals=signals,
        )
    finally:
        doc.close()
