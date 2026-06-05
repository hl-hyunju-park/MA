"""LLM parse pass: a sheet's Markdown grid -> a grounded structural schema.

This is the *interpretation* half of the pipeline (the *extraction* half — cells,
values, formula edges — stays mechanical in ``extract.py``). It replaces the brittle
hand-curated layout logic in ``metrics.py`` (per-sheet ``fiscal_year_axis`` offsets,
hand-keyed anchor cells) with an LLM reading the 2D grid produced by
``dump_md.py``.

The contract follows CLAUDE.md's rules for LLM use:
  - The model **interprets structure** (which row is the year axis, which rows are
    line items, what each line means, KO/EN aliases). It returns **cell references**,
    never numbers — values are read from openpyxl, never transcribed by the model.
  - Every reference the model emits is **grounded** against the real workbook cells
    (OpenKB whitelist pattern, applied to parsing): a label must actually sit at the
    cell the model cites; an axis cell must actually hold a year. Ungrounded claims are
    dropped and recorded, never trusted.

Output per sheet -> ``data/parsed/<sheet>.json``:
    {meta:{title,unit,case}, year_axis:{row,columns:{COL:year}}, line_items:[...],
     grounding:{...}}

Usage (from repo root, venv active; needs the local vLLM up — see llm.py):
    python -m src.stella_kb.wiki.dump_md --all      # produce data/md/ first
    python -m src.stella_kb.wiki.parse_llm "DCF"    # parse one sheet
    python -m src.stella_kb.wiki.parse_llm --all    # parse every dumped sheet
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl

from .. import WORKBOOK
from ..llm import chat
from ..prompts import load as load_prompt

MD_DIR = Path("data/md")
OUT_DIR = Path("data/parsed")

_CELL = re.compile(r"^([A-Z]{1,3})(\d+)$")


# --------------------------------------------------------------------------- prompt

_SYSTEM = load_prompt("parse_system")


def _values_grid(md: str) -> str:
    """The values grid (+ merged ranges), without the long formulas appendix."""
    return md.split("\n## Formulas", 1)[0]


def _json_from(raw: str) -> dict | None:
    """Extract the first JSON object from a model reply (tolerates ```json fences)."""
    s = raw.strip()
    if "```" in s:
        parts = s.split("```")
        s = max(parts, key=len).lstrip("json").strip() if len(parts) >= 3 else s.strip("`")
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(s[start:end + 1])
    except (ValueError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- grounding

def load_values(sheet: str) -> dict[str, object]:
    """``{coordinate: cached value}`` for a sheet — the ground truth for validation."""
    wb = openpyxl.load_workbook(WORKBOOK, data_only=True, read_only=True)
    ws = wb[sheet]
    vals = {c.coordinate: c.value for row in ws.iter_rows() for c in row
            if c.value is not None}
    wb.close()
    return vals


def _norm(text: object) -> str:
    return re.sub(r"\s+", "", str(text)).casefold()


def _year_at(value: object) -> object | None:
    """The year a cell represents, if any (int year, or a date's year)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (datetime, date)):
        return value.year
    if isinstance(value, (int, float)) and 2000 <= int(value) <= 2040:
        return int(value)
    if isinstance(value, str):
        if value.strip() in {"T.V.", "Terminal", "n/a"}:
            return value.strip()
        m = re.search(r"\b(20[0-3]\d)\b", value)
        if m:
            return int(m.group(1))
    return None


def ground(parsed: dict, values: dict[str, object]) -> dict:
    """Drop every claim that doesn't match a real cell; keep a report of what fell out.

    Mutates ``parsed`` in place and returns a grounding summary. The axis column->year
    map is *derived* from the cells in the LLM-named row (the model never counts columns,
    so off-by-one is impossible); a line-item label is grounded if the cited cell's text
    contains the label (or vice versa).
    """
    report = {"dropped_items": [], "axis_row_ok": None}

    axis = parsed.get("year_axis") or {}
    row = axis.get("row")
    cols = {}
    if row:
        for coord, val in values.items():
            m = _CELL.match(coord)
            if m and int(m.group(2)) == row:
                year = _year_at(val)
                if year is not None:
                    cols[m.group(1)] = year
    parsed["year_axis"] = {"row": row, "columns": cols}
    report["axis_row_ok"] = bool(cols)
    report["kept_axis_cols"] = len(cols)

    kept_items = []
    for item in parsed.get("line_items", []):
        cell = (item.get("label_cell") or "").upper()
        label = item.get("label") or item.get("label_en") or ""
        cell_text = values.get(cell)
        m = _CELL.match(cell)
        in_axis_row = bool(m) and row is not None and int(m.group(2)) == row
        ok = bool(m) and not in_axis_row and cell_text is not None and label and (
            _norm(label) in _norm(cell_text) or _norm(cell_text) in _norm(label))
        if ok:
            kept_items.append(item)
        else:
            report["dropped_items"].append({"label": label, "label_cell": cell,
                                            "cell_text": cell_text})
    parsed["line_items"] = kept_items
    report["kept_items"] = len(kept_items)
    return report


# --------------------------------------------------------------------------- driver

def parse_sheet(sheet: str, timeout: float = 600.0) -> dict:
    """Parse one sheet: read its md dump, call the LLM, ground the result."""
    md_path = MD_DIR / f"{sheet.replace('/', '_')}.md"
    if not md_path.exists():
        raise FileNotFoundError(f"{md_path} — run `python -m src.stella_kb.wiki.dump_md` first")
    grid = _values_grid(md_path.read_text(encoding="utf-8"))

    raw = chat(
        [{"role": "system", "content": _SYSTEM},
         {"role": "user", "content": f"Worksheet: {sheet!r}\n\n{grid}\n\nJSON:"}],
        max_tokens=4096, timeout=timeout,
    )
    parsed = _json_from(raw)
    if parsed is None:
        return {"sheet": sheet, "error": "no JSON parsed", "raw": raw[:2000]}

    parsed["sheet"] = sheet
    parsed["grounding"] = ground(parsed, load_values(sheet))
    return parsed


def _parse_and_write(name: str) -> str:
    """Parse one sheet and write its JSON; return a one-line status (thread worker)."""
    try:
        result = parse_sheet(name)
    except Exception as e:  # noqa: BLE001 — report per-sheet, keep going
        return f"!! {name}: {type(e).__name__}: {e}"
    if "error" in result:
        return f"!! {name}: {result['error']}"
    out = OUT_DIR / f"{name.replace('/', '_')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    g = result["grounding"]
    return (f"{name}: {g['kept_items']} items, {g['kept_axis_cols']} axis cols "
            f"(dropped {len(g['dropped_items'])} items) -> {out.name}")


if __name__ == "__main__":
    import sys

    # Divider tabs dump to near-empty stubs; skip them in a full run.
    args = sys.argv[1:]
    if args and args[0] == "--all":
        sheets = [p.stem for p in sorted(MD_DIR.glob("*.md"))
                  if p.stat().st_size > 200]
    else:
        sheets = args or ["DCF"]

    # Concurrent requests — vLLM batches them, so throughput >> sequential. Bounded to
    # keep load light on the shared endpoint (override with STELLA_CONCURRENCY).
    workers = max(1, min(int(os.environ.get("STELLA_CONCURRENCY", "6")), len(sheets)))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"parsing {len(sheets)} sheets with {workers} concurrent workers ...")
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for msg in ex.map(_parse_and_write, sheets):
            print(msg, flush=True)
