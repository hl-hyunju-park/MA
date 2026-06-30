"""Agent-side scaling fixes that make a large document-data-room dataset (v0.3) servable.

Three deterministic, offline behaviours — no network — added so a 2,000-page dumped-grid wiki
answers as well as the small formula-model wikis (v0.1/v0.2):

1. ``compact_outline`` — the per-page INDEX.md overflows a planner/router prompt once a corpus is
   huge, so past a size threshold it collapses to the heading-only section outline (small corpora
   stay byte-for-byte unchanged).
2. ``lookup_pages`` + ``_expand_section`` / lookup fallback — with only the heading outline the
   router picks a *section* name, not a page key; we expand that to the real pages under it and,
   if the LLM whiffs entirely, fall back to the alias lookup's own candidates.
3. ``_cell_on_page`` positional match — dumped grids encode a cell coordinate by position
   (column-letter header + row-number label), never as the literal ``E20`` the formula-model
   pages carry, so the provenance guard learns to verify position too.
"""

from __future__ import annotations

from apps.agent.cores.wiki.engine import _cell_on_page
from apps.agent.cores.wiki.solve import _expand_section
from apps.agent.retrieval import lookup_pages
from apps.agent.utils.datasets import INDEX_MD_MAX_CHARS, compact_outline


# --- compact_outline: full ToC for small corpora, heading-only for huge ones ---------------
def test_compact_outline_keeps_small_index_verbatim():
    md = "# Wiki\n## Sheet A\n- **[[A]]** — desc\n  - ledger\n## Sheet B\n- **[[B]]** — desc\n"
    assert compact_outline(md) == md  # under the threshold → unchanged, byte-for-byte


def test_compact_outline_collapses_large_index_to_headings():
    # A ToC well past the threshold: many per-page bullet lines under a few section headings.
    bullets = "".join(f"- **[[page_{i}]]** — row {i}\n  - ledger\n" for i in range(4000))
    md = f"# Wiki\n## 1. 회사\n### 1.1. 경영실태평가\n{bullets}## 2. 재무\n### 2.1. K-ICS\n{bullets}"
    assert len(md) > INDEX_MD_MAX_CHARS
    out = compact_outline(md)
    assert "[[page_0]]" not in out and "ledger" not in out      # bullets dropped
    for h in ("# Wiki", "## 1. 회사", "### 1.1. 경영실태평가", "## 2. 재무", "### 2.1. K-ICS"):
        assert h in out                                          # every heading kept
    assert len(out) < len(md)


# --- lookup_pages + _expand_section: section heading → real page keys -----------------------
def _grid_index():
    """A tiny index whose aliases are full row labels (``10. 지급여력비율``) keyed under
    several monthly pages in one section — the data-room shape that defeats an exact lookup."""
    pages = {
        "1.1. 경영실태평가__경영실태평가_202303": {"kind": "ledger"},
        "1.1. 경영실태평가__경영실태평가_202306": {"kind": "ledger"},
        "2.1.2. K-ICS BS__23년말 K-ICS BS": {"kind": "ledger"},
        "unrelated__other": {"kind": "ledger"},
    }
    alias_index = {
        "10.지급여력비율": [
            {"page": "1.1. 경영실태평가__경영실태평가_202303", "cell": "B20", "term": "10. 지급여력비율"},
            {"page": "1.1. 경영실태평가__경영실태평가_202306", "cell": "B20", "term": "10. 지급여력비율"},
        ],
        "k-ics지급여력비율(총괄)": [
            {"page": "2.1.2. K-ICS BS__23년말 K-ICS BS", "cell": "A3", "term": "K-ICS 지급여력비율(총괄)"},
        ],
    }
    return {"pages": pages, "alias_index": alias_index}


def test_lookup_pages_resolves_substring_term_to_pages():
    idx = _grid_index()
    # bare '지급여력비율' is a substring of the enumerated alias keys → both monthly pages + K-ICS
    pgs = lookup_pages(idx, ["지급여력비율"])
    assert "1.1. 경영실태평가__경영실태평가_202303" in pgs
    assert "1.1. 경영실태평가__경영실태평가_202306" in pgs
    assert "2.1.2. K-ICS BS__23년말 K-ICS BS" in pgs
    assert "unrelated__other" not in pgs
    assert len(pgs) == len(set(pgs))  # deduped


def test_expand_section_maps_heading_pick_to_its_pages():
    cand = lookup_pages(_grid_index(), ["지급여력비율"])
    # router picked the section heading (from the compact outline), not a page key
    exp = _expand_section("1.1. 경영실태평가", cand)
    assert set(exp) == {
        "1.1. 경영실태평가__경영실태평가_202303",
        "1.1. 경영실태평가__경영실태평가_202306",
    }
    assert _expand_section("nonexistent section", cand) == []      # no false expansion
    assert _expand_section("2.1.2. K-ICS BS", cand) == ["2.1.2. K-ICS BS__23년말 K-ICS BS"]


# --- _cell_on_page: literal (formula-model) AND positional (dumped grid) --------------------
_GRID_PAGE = (
    "# 1.1. 경영실태평가__경영실태평가_202503\n\n## Values\n\n"
    "| | A | B | C | D | E |\n|---|---|---|---|---|---|\n"
    "| **20** | A12 | 10. 지급여력비율 | 1408972952 | 859398919 | 163.95 |\n"
)
_LITERAL_PAGE = "관리수수료 합계 12,345 [E20] 기준."


def test_cell_on_page_literal_still_matches():
    assert _cell_on_page("E20", _LITERAL_PAGE) is True
    assert _cell_on_page("E2", _LITERAL_PAGE) is False   # boundary guard: E2 ≠ E20


def test_cell_on_page_positional_grid_match():
    assert _cell_on_page("E20", _GRID_PAGE) is True      # col E heads a column, row 20 is labelled
    assert _cell_on_page("C20", _GRID_PAGE) is True      # any real column on a real row


def test_cell_on_page_rejects_absent_coordinate():
    assert _cell_on_page("E99", _GRID_PAGE) is False     # row 99 not on the page → hallucination
    assert _cell_on_page("Z20", _GRID_PAGE) is False     # column Z not in the header → hallucination
    assert _cell_on_page("notacell", _GRID_PAGE) is False


# the case the OLD independent col/row check waved through: column E and row 20 both present, but
# their intersection (the E-cell on row 20) is EMPTY → the cite is not actually backed by a value.
_GRID_EMPTY_E20 = (
    "# grid\n\n## Values\n\n"
    "| | A | B | C | D | E |\n|---|---|---|---|---|---|\n"
    "| **20** | A12 | 10. 지급여력비율 | 1408972952 | 859398919 |  |\n"   # E (last) cell blank
)


def test_cell_on_page_empty_intersection_rejected():
    assert _cell_on_page("E20", _GRID_EMPTY_E20) is False   # E20 blank → reject (the real fix)
    assert _cell_on_page("C20", _GRID_EMPTY_E20) is True    # C20 still filled → accept


def test_cell_on_page_intersection_needs_both_on_same_grid():
    # column E exists (in grid 1) and row 20 exists (in grid 2), but never together → reject
    two_grids = (
        "## Values\n\n| | A | E |\n|---|---|---|\n| **5** | x | y |\n\n"   # has col E, row 5 (not 20)
        "## Values\n\n| | A | B |\n|---|---|---|\n| **20** | p | q |\n"     # has row 20, no col E
    )
    assert _cell_on_page("E20", two_grids) is False
    assert _cell_on_page("E5", two_grids) is True           # E5 is a real filled intersection
