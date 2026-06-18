"""Deduplicate the alias index — two deterministic, offline passes.

``alias_index`` maps a normalized term → ``[{page, cell, term}]``. The parse LLM over-generates
aliases (e.g. a balance-sheet row gets ``Accounts Receivable`` / ``Accounts Receivable Gross`` /
``Gross Accounts Receivable`` + check rows), and aggregate labels (``합계``/``Total``) repeat on
every page. This pass cleans both **without** harming retrieval:

  1. **Structural stopword removal** — drop aggregate/layout/scaffolding terms (``합계``, ``소계``,
     ``구분``, ``기타``, ``Total``, ``Category``, ``Key Issue``, ``Balance Check`` …). These hit
     nearly every page, carry zero routing signal, and crowd real hits out of the lookup window.

  2. **Same-cell reorder collapse** — within one ``(page, cell)``, alias terms that are pure
     word-order permutations of each other (identical token *set*, e.g. ``X Gross`` ≡ ``Gross X``)
     are merged to one canonical key. Scoped to a single cell so it only ever removes a genuine
     restatement of the *same* line item; ``lookup`` already dedups results by ``(page, cell)``,
     so this shrinks the index without changing query results. It will NOT merge distinct metrics
     (``관리보수`` vs ``관리보수율`` have different token sets; net vs gross are different cells).

What it deliberately KEEPS: genuine synonyms / KO↔EN / long-short variants (``현금및현금성자산`` /
``Cash``; ``Allowance for AR`` / ``Allowance for Doubtful Accounts (AR)``) — those are recall, and
the dropped *reorderings* a user might still type are covered by the query-time fuzzy tier.

Runs at the end of ``build_index`` (fresh builds are clean) and standalone to retrofit existing
``index.json`` files without a rebuild:

    python -m src.stella_kb.wiki.dedup                 # dry-run report on the build index
    python -m src.stella_kb.wiki.dedup --fix PATH ...  # prune the given index.json file(s)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _norm(term: str) -> str:
    """Match index.py's alias-key normalization exactly (whitespace-strip + casefold)."""
    return re.sub(r"\s+", "", term).casefold()


def _token_set(term: str) -> frozenset[str]:
    """Word tokens of an alias (alnum runs, casefolded) — order-insensitive. ``GP관리보수`` and
    Korean labels are single-token so they never reorder-collapse; multi-word English does."""
    return frozenset(t for t in re.findall(r"\w+", term.casefold(), re.UNICODE) if t)


_RAW_STOPWORDS = [
    # KO totals / aggregates
    "합계", "소계", "총계", "누계", "총비용", "총수익", "계",
    # KO layout / catch-all
    "구분", "항목", "비고", "기타",
    # EN totals / aggregates
    "total", "totals", "subtotal", "sub total", "grand total", "sum",
    "total expenses", "total revenue", "total cost", "total costs",
    "total assets", "total liabilities", "total equity", "total liabilities and equity", "total l&e",
    # EN layout / generic
    "other", "others", "misc",
    # check / balance rows
    "balance check", "bs balance check", "bs 합계 check", "check",
    # FDD page-structure scaffolding (vision parser emits these as aliases)
    "category", "key issue", "key issues", "key finding", "key findings",
    "key finding summary", "implication", "implications", "summary", "note", "notes",
]
STRUCTURAL_STOPWORDS = frozenset(_norm(s) for s in _RAW_STOPWORDS)


def analyze(index: dict, top: int = 15) -> dict:
    """Overlap stats for an ``index`` dict — for the dry-run report (no mutation)."""
    ai = index.get("alias_index") or {}
    pages_per = {k: len({h["page"] for h in v}) for k, v in ai.items()}
    overlapping = sorted(((k, c) for k, c in pages_per.items() if c > 1), key=lambda kv: -kv[1])
    return {
        "alias_terms": len(ai),
        "overlapping_terms": len(overlapping),
        "max_pages": overlapping[0][1] if overlapping else 0,
        "top": overlapping[:top],
        "stopwords_present": sorted(t for t in ai if t in STRUCTURAL_STOPWORDS),
    }


def dedup_alias_index(index: dict, extra_stopwords: tuple[str, ...] = ()) -> dict:
    """Run both passes on ``index`` (mutates in place); return a prune report. Idempotent."""
    stop = STRUCTURAL_STOPWORDS | {_norm(s) for s in extra_stopwords if s}
    ai = index.get("alias_index") or {}

    # pass 1 — structural stopwords
    removed_stop = sorted(t for t in ai if t in stop)
    stop_hits = sum(len(ai[t]) for t in removed_stop)
    for t in removed_stop:
        del ai[t]

    # pass 2 — same-(page,cell) reorder collapse
    cellmap: dict[tuple, list[tuple[str, str]]] = {}
    for key, hits in ai.items():
        for h in hits:
            cellmap.setdefault((h["page"], h.get("cell")), []).append((key, h.get("term", key)))
    drop: dict[str, set] = {}     # key -> {(page, cell), ...} hits to remove
    collapsed = 0
    for sig, entries in cellmap.items():
        groups: dict[frozenset, list[str]] = {}
        for key, term in entries:
            ts = _token_set(term)
            if len(ts) < 2:       # single-token can't be a reordering
                continue
            groups.setdefault(ts, []).append(key)
        for ts, keys in groups.items():
            uniq = sorted(set(keys))
            if len(uniq) < 2:
                continue
            for k in uniq[1:]:    # keep uniq[0] as canonical (deterministic)
                drop.setdefault(k, set()).add(sig)
                collapsed += 1
    for k, sigs in drop.items():
        ai[k] = [h for h in ai[k] if (h["page"], h.get("cell")) not in sigs]
        if not ai[k]:
            del ai[k]

    # keep per-page alias lists consistent: a page alias must still be a live alias_index key
    valid = set(ai)
    page_pruned = 0
    for p in (index.get("pages") or {}).values():
        before = p.get("aliases") or []
        kept = [a for a in before if _norm(a) in valid]
        if len(kept) != len(before):
            page_pruned += len(before) - len(kept)
            p["aliases"] = kept

    return {"stopword_terms_removed": removed_stop, "stopword_hits_removed": stop_hits,
            "reorder_hits_collapsed": collapsed, "page_aliases_pruned": page_pruned,
            "alias_terms_after": len(ai)}


def _report(title: str, index: dict) -> None:
    a = analyze(index)
    print(f"{title}: {a['alias_terms']} terms · {a['overlapping_terms']} overlap (>1 page) · "
          f"max {a['max_pages']}p · {len(a['stopwords_present'])} stopword term(s) present")


if __name__ == "__main__":
    from ..config import wiki_index_json

    fix = "--fix" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--fix"]
    paths = [Path(a) for a in args] or [wiki_index_json()]
    try:
        from ..config import alias_stopwords
        extra = tuple(alias_stopwords())
    except Exception:  # noqa: BLE001 — accessor optional
        extra = ()
    for path in paths:
        if not path.exists():
            print(f"dedup: {path} not found — skipping")
            continue
        index = json.loads(path.read_text(encoding="utf-8"))
        _report(f"BEFORE {path}", index)
        if fix:
            rep = dedup_alias_index(index, extra)
            path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  --fix: removed {len(rep['stopword_terms_removed'])} stopword term(s) "
                  f"({rep['stopword_hits_removed']} hits), collapsed {rep['reorder_hits_collapsed']} "
                  f"reorder hit(s), pruned {rep['page_aliases_pruned']} page alias(es)")
            _report(f"AFTER  {path}", index)
        else:
            would = sorted(t for t in (index.get("alias_index") or {})
                           if t in (STRUCTURAL_STOPWORDS | {_norm(s) for s in extra}))
            print(f"  dry-run: would remove {len(would)} stopword term(s); pass --fix to apply")
