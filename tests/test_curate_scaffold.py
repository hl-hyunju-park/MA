"""Deterministic offline tests for the curation scaffolder (no network, no LLM).

Covers the safety-critical behaviours: routes come from STRUCTURAL identity (subsection names +
unique PDF doc tokens) never raw cell contents; time-series subsections and generic/ambiguous
terms are excluded; decks pin each PDF lead page.
"""

from __future__ import annotations

import json

from src.stella_kb.wiki.curate_scaffold import (
    _is_clean_term,
    scaffold_decks,
    scaffold_routes,
    write_files,
)


def _idx() -> dict:
    """A tiny index exercising every routing path: a small (routable) subsection, a large
    time-series subsection, a metric row label, a unique PDF doc token, and an ambiguous one."""
    pages = {
        # small subsection (2 pages) → routable
        "2.1.2. K-ICS BS__23년말 K-ICS BS": {"source": "XLSX"},
        "2.1.2. K-ICS BS__24년말 K-ICS BS": {"source": "XLSX"},
        # large time-series subsection (5 pages) → NOT routed
        **{f"1.1. 경영실태평가__경영실태평가_20240{i}": {"source": "XLSX"} for i in range(1, 6)},
        # PDF docs: one with a unique subject token, two sharing a folder (회계정책서)
        "FDD1 — [1.3. 정관 및 사규 _ (1-100) 정관 20250331] 총칙": {"source": "PDF"},
        "FDD1 — [1.6. 회계정책서 _ KDB생명_회계정책서_금융상품] 표지": {"source": "PDF"},
        "FDD1 — [1.6. 회계정책서 _ KDB생명_회계정책서_리스] 표지": {"source": "PDF"},
    }
    alias_index = {
        # a metric row label living on many pages — must never become a route
        "10.지급여력비율": [{"page": f"1.1. 경영실태평가__경영실태평가_20240{i}", "cell": "E20",
                          "term": "10. 지급여력비율"} for i in range(1, 6)],
    }
    documents = {
        "1.3. 정관 및 사규 _ (1-100) 정관 20250331": {"title": "정관"},
        "1.6. 회계정책서 _ KDB생명_회계정책서_금융상품": {"title": "금융상품 정책서"},
        "1.6. 회계정책서 _ KDB생명_회계정책서_리스": {"title": "리스 정책서"},
    }
    return {"pages": pages, "alias_index": alias_index, "documents": documents}


def test_clean_term_filters():
    assert _is_clean_term("정관")                      # plain concept
    assert _is_clean_term("K-ICS BS")                 # ASCII+digits, long enough
    assert not _is_clean_term("10. 지급여력비율")        # leading enumerator
    assert not _is_clean_term("2024")                  # bare year
    assert not _is_clean_term("FY2023")                # fiscal-year token
    assert not _is_clean_term("KDB")                   # short pure-ASCII acronym
    assert not _is_clean_term("현황")                   # generic noun (stoplist)
    assert not _is_clean_term("a")                     # too short


def test_routes_are_structural_not_metric():
    routes = scaffold_routes(_idx())
    # small subsection routed to BOTH its pages
    assert set(routes["K-ICS BS"]) == {
        "2.1.2. K-ICS BS__23년말 K-ICS BS", "2.1.2. K-ICS BS__24년말 K-ICS BS"}
    # the time-series metric is NEVER a route key (the whole point)
    assert "지급여력비율" not in routes
    assert "10. 지급여력비율" not in routes
    assert "경영실태평가" not in routes      # 5-page subsection > _MAX_FANOUT → skipped


def test_routes_pdf_unique_token_only():
    routes = scaffold_routes(_idx())
    # '정관' is unique to one doc → routed to its lead page
    assert routes["정관"] == ["FDD1 — [1.3. 정관 및 사규 _ (1-100) 정관 20250331] 총칙"]
    # subject tokens unique to one 회계정책서 doc are kept...
    assert "금융상품" in routes and "리스" in routes
    # ...but '회계정책서' spans both docs → ambiguous → dropped
    assert "회계정책서" not in routes
    # every target is a real page, single-valued routes resolve to one page
    pages = set(_idx()["pages"])
    assert all(t in pages for v in routes.values() for t in v)


def test_decks_pin_lead_pages():
    decks = scaffold_decks(_idx())
    assert set(decks) == set(_idx()["documents"])         # one block per PDF doc
    blk = decks["1.3. 정관 및 사규 _ (1-100) 정관 20250331"]
    assert blk["title"] == "정관"
    assert blk["pages"] == {1: "총칙"}                     # FDD1 label pinned


def test_write_files_roundtrip(tmp_path):
    import yaml
    idx = _idx()
    n_r, n_d = write_files(idx, tmp_path / "decks.yaml", tmp_path / "routes.yaml")
    assert n_r > 0 and n_d == 3
    # files parse, single-page routes render as scalars, multi-page as lists
    routes = yaml.safe_load((tmp_path / "routes.yaml").read_text())
    assert isinstance(routes["정관"], str)                 # 1 page → scalar
    assert isinstance(routes["K-ICS BS"], list)            # 2 pages → list
    decks = yaml.safe_load((tmp_path / "decks.yaml").read_text())
    assert decks["1.3. 정관 및 사규 _ (1-100) 정관 20250331"]["pages"] == {1: "총칙"}
