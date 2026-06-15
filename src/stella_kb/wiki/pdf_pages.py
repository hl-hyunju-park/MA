"""Ingest a PDF report into wiki pages — the counterpart to the Excel pipeline.

A summary PDF (e.g. an FDD Executive Summary) is the *other* document in a PDF×Excel
cross-check. This stage lifts the PDF into wiki pages so the agent can open a PDF page
**and** an Excel page and compare — the same retrieval path, no agent changes.

Flow (mirrors dump_md -> parse_llm -> compile):
  1. the **vision PDF parser** (``parsers.pdf.describe_pdf`` — gemma multimodal) reads each
     page *image* into faithful **markdown** (tables as pipe-rows, charts, reading order).
     Slide-deck FDD reports parse far better this way than via text extraction.
  2. each PDF **page** becomes one **section** (``pdf_to_sections``); its label comes from the
     page's ``# Executive Summary | <name>`` heading — Company Snapshot, Key Finding Summary,
     Valuation Summary, … — one wiki page per PDF page.
  3. the LLM structures each section into {title, aliases, figures[], summary} — it interprets,
     never transcribes numbers (values copied verbatim from the markdown, CLAUDE.md rule).
  4. every figure value is **grounded**: its digits must appear in the section text, else dropped.
  5. each value is rendered with a ``[<tag>]`` source marker (the PDF analogue of the Excel
     ``[J6]`` cell) so the retriever's cell-on-page guard passes unchanged.

``build_pages`` returns the index pieces (page entries, alias additions, tree section) for the
caller to merge into an existing wiki ``index.json`` next to the Excel pages.

Requires the vision endpoint (gemma-4 vLLM, ``STELLA_LLM_URL``) + PyMuPDF/pdfplumber.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..llm import _json_span, chat
from ..prompts import load as load_prompt

_SYSTEM = load_prompt("pdf_page_system")
SECTION = "FDD 요약 보고서 (PDF)"
_HEADING = re.compile(r"^#{1,3}\s+(.*\S)\s*$", re.M)


def _label_from_page(md: str) -> str:
    """Derive a section label from a vision page's first markdown heading.

    The FDD pages carry a ``# Executive Summary | <name>`` title; strip the boilerplate
    ``Executive Summary |`` prefix and any ``[FDD]`` suffix."""
    m = _HEADING.search(md)
    if not m:
        return ""
    label = re.sub(r"Executive Summary\s*\|", "", m.group(1)).strip()
    label = re.sub(r"\s*\[FDD\].*$", "", label).strip()
    return label


def pdf_to_sections(pdf_path: str, min_chars: int = 200) -> list[tuple[str, str]]:
    """Vision-parse the PDF (gemma multimodal) into ``[(label, body), ...]`` — one per page.

    The vision parser emits faithful per-page markdown (tables, charts, reading order) for
    these slide-deck FDD reports, so each PDF page becomes one wiki section. Short pages
    (covers/dividers, < ``min_chars``) are dropped; a duplicate label gets a ``#n`` suffix so
    page names stay unique."""
    from ..parsers.pdf import describe_pdf

    pages, _ = describe_pdf(pdf_path)
    out: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    for sp in pages:
        body = sp.text.strip()
        if len(body) < min_chars:
            continue
        label = _label_from_page(body) or f"페이지 {sp.page}"
        seen[label] = seen.get(label, 0) + 1
        if seen[label] > 1:
            label = f"{label} #{seen[label]}"
        out.append((label, body))
    return out


def _clean(s: object) -> str:
    return re.sub(r"[\s,]", "", str(s))


def _grounded(value: str, text: str) -> bool:
    """Keep a figure only if its (comma/space-stripped) value occurs in the section text —
    the OpenKB whitelist idea applied to PDF: the model may label, but can't invent numbers."""
    v = _clean(value)
    return len(v) >= 2 and v in _clean(text)


def structure_section(label: str, text: str, timeout: float = 600.0) -> dict:
    """LLM-structure one section's markdown; drop ungrounded figures. ``{}`` if unusable."""
    raw = chat(
        [{"role": "system", "content": _SYSTEM},
         {"role": "user", "content": f"PDF 섹션: {label!r}\n\n{text}\n\nJSON:"}],
        max_tokens=3500, timeout=timeout,
    )
    obj = _json_span(raw, "{", "}")
    if not isinstance(obj, dict):
        return {}
    obj["figures"] = [f for f in (obj.get("figures") or [])
                      if isinstance(f, dict) and f.get("value") and _grounded(f["value"], text)]
    return obj


def _page_md(name: str, tag: str, label: str, s: dict) -> str:
    title = s.get("title") or label
    aliases = [a for a in (s.get("aliases") or []) if a]
    out = ["---", "source: PDF", f"page: {name}", f"tag: {tag}", f"section: {label}"]
    if aliases:
        out.append("aliases: [" + ", ".join(aliases) + "]")
    out += ["---", "", f"# {name}", "",
            f"> 출처: FDD&Valuation Report Executive Summary — {label} (`{tag}`). "
            "**PDF 요약 수치이며 엑셀 원천과 정의·기준이 다를 수 있습니다**(예: 영업수익 Total은 "
            "배당금 포함; 보고서 기준일은 Jun-24).", "",
            "## What this is", "", (s.get("summary") or "_(요약 없음)_"), "",
            "## Key figures (PDF 보고서 수치)", "",
            "| 항목 | 기간 | value |", "|---|---|---|"]
    for f in s.get("figures") or []:
        out.append(f"| {f.get('label','')} | {f.get('period','') or ''} | {f.get('value','')} [{tag}] |")
    out += ["", "## Links", "",
            "- PDF 요약 — 동일 항목의 **엑셀 원천 페이지와 교차검증** 대상 (단위·기준일 차이 주의)."]
    return "\n".join(out) + "\n"


def build_pages(pdf_path: str, pages_dir: Path, structurer=structure_section) -> tuple[dict, dict, dict]:
    """Build PDF wiki pages and the index pieces to merge into an existing wiki index.

    Returns ``(pages_entries, alias_additions, tree_section)`` and writes ``<name>.md`` into
    ``pages_dir``. One page per markdown H2 section; each tagged ``FDD<n>`` for provenance.
    """
    from concurrent.futures import ThreadPoolExecutor

    pages_dir.mkdir(parents=True, exist_ok=True)
    sections = pdf_to_sections(pdf_path)

    with ThreadPoolExecutor(max_workers=6) as ex:  # one LLM call per section, bounded
        structured = list(ex.map(lambda ls: (ls[0], ls[1], structurer(ls[0], ls[1])), sections))

    entries: dict[str, dict] = {}
    aliases: dict[str, list] = {}
    tree: dict[str, dict] = {SECTION: {}}
    for i, (label, text, s) in enumerate(structured, 1):  # number by section position (stable)
        figs = s.get("figures") or []
        if not figs and not (s.get("aliases") or []):
            continue  # nothing structured (cover/divider section) — keeps the FDD{i} slot
        tag = f"FDD{i}"
        name = f"FDD{i} — {label}"
        (pages_dir / f"{name}.md").write_text(_page_md(name, tag, label, s), encoding="utf-8")

        page_aliases = [a for a in (s.get("aliases") or []) if a]
        labels = [f.get("label") for f in figs if f.get("label")]
        entries[name] = {
            "sheet": name, "title": s.get("title") or label,
            "desc": (s.get("summary") or "").split(". ")[0][:120] or None,
            "section": SECTION, "group": label, "kind": "pdf 요약", "case": None,
            "unit": None, "period": "Dec-20–Jun-24", "data_status": None,
            "n_items": len(figs), "has_page": True, "aliases": page_aliases,
            "items": [{"label": lb, "ko": None, "cell": tag, "role": "pdf"} for lb in labels],
            "depends_on": [], "feeds_into": [], "source": "PDF",
        }
        for term in page_aliases + labels:
            key = re.sub(r"\s+", "", str(term)).casefold()
            aliases.setdefault(key, []).append({"page": name, "cell": tag, "term": term})
        tree[SECTION].setdefault(label, []).append(name)

    return entries, aliases, tree


def strip_pdf(index: dict) -> dict:
    """Remove all PDF artifacts from a wiki index (pages, their alias entries, the PDF tree
    section) so a rebuild replaces cleanly instead of accumulating stale pages."""
    pdf = {n for n, e in index["pages"].items() if e.get("source") == "PDF"}
    for n in pdf:
        index["pages"].pop(n, None)
    index["tree"].pop(SECTION, None)
    ai = index["alias_index"]
    for key in list(ai):
        kept = [h for h in ai[key] if h["page"] not in pdf]
        if kept:
            ai[key] = kept
        else:
            del ai[key]
    return index


def merge_into_index(index: dict, entries: dict, alias_add: dict, tree_add: dict) -> dict:
    """Merge PDF pieces into a loaded wiki index dict (in place) and return it."""
    index["pages"].update(entries)
    ai = index["alias_index"]
    for key, bucket in alias_add.items():
        ai.setdefault(key, []).extend(
            b for b in bucket
            if not any(h["page"] == b["page"] and h["cell"] == b["cell"] for h in ai.get(key, [])))
    for section, groups in tree_add.items():
        dst = index["tree"].setdefault(section, {})
        for g, names in groups.items():
            dst.setdefault(g, []).extend(nm for nm in names if nm not in dst.get(g, []))
    return index


if __name__ == "__main__":
    # Stage 5 of run_pipeline.sh: ingest every PDF report under data/raw/ and merge its pages
    # into the index the Excel pipeline already built (stage 4). Self-skips cleanly when there
    # is no PDF, so the stage is always safe to run. Mirrors eval.stella_crosscheck.build_pdf.
    import json
    import sys

    from .index import OUT_JSON, OUT_MD, PAGES_DIR, render_md

    pdfs = [str(p) for p in sorted(Path("data/raw").glob("*.pdf"))]
    if len(sys.argv) > 1:                                  # explicit path(s) override the glob
        pdfs = sys.argv[1:]
    if not pdfs:
        print("pdf_pages: no data/raw/*.pdf — skipping PDF ingest.")
        sys.exit(0)
    if not OUT_JSON.exists():
        sys.exit(f"pdf_pages: {OUT_JSON} not found — run the index stage (4) first.")

    for stale in PAGES_DIR.glob("FDD*.md"):                # clean slate so a rebuild replaces
        stale.unlink()
    index = json.loads(OUT_JSON.read_text(encoding="utf-8"))
    index = strip_pdf(index)                               # drop any prior PDF entries first
    for pdf in pdfs:
        print(f"pdf_pages: ingest {pdf}")
        entries, alias_add, tree_add = build_pages(pdf, PAGES_DIR)
        merge_into_index(index, entries, alias_add, tree_add)
        print(f"   built {len(entries)} PDF page(s): {list(entries)}")

    OUT_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(index), encoding="utf-8")
    print(f"pdf_pages: merged -> {OUT_JSON}  (pages={len(index['pages'])}, "
          f"aliases={len(index['alias_index'])})")
