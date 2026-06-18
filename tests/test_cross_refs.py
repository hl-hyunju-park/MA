"""Directed PDF→Excel cross-refs — entity gate, specificity, bipartite, via, judge. Offline."""

from __future__ import annotations

import pytest

from src.stella_kb.wiki.cross_refs import build_cross_refs


@pytest.fixture(autouse=True)
def _no_fund_xref(monkeypatch):
    # isolate Tier B / Gate 0: stub Tier-A fund identity to empty (tested separately in build)
    from src.stella_kb.wiki import pdf_pages
    monkeypatch.setattr(pdf_pages, "_xrefs", lambda f, index: [])


def _idx() -> dict:
    return {
        "documents": {
            "STELLA": {"title": "Project Stella", "description": "센트로이드 인베스트먼트파트너스 FDD"},
            "CAESAR": {"title": "Project CAESAR", "description": "Celadon Partners LLC valuation"},
        },
        "pages": {
            "WACC 장표": {"aliases": ["WACC", "가중평균자본비용"], "items": [{"label": "WACC"}]},
            "제2호_비용": {"aliases": ["관리보수"], "items": [{"label": "관리보수"}]},
            "FDD17 — [STELLA] DCF Summary": {"source": "PDF", "aliases": ["WACC"], "items": []},
            "FDD8 — [CAESAR] WACC": {"source": "PDF", "aliases": ["WACC"], "items": []},
            "FDD5 — [STELLA] Related Party": {"source": "PDF", "aliases": ["관리보수"], "items": []},
        },
        "alias_index": {
            "wacc": [{"page": "WACC 장표", "cell": "B1"},
                     {"page": "FDD17 — [STELLA] DCF Summary", "cell": "FDD17"},
                     {"page": "FDD8 — [CAESAR] WACC", "cell": "FDD8"}],          # 3 pages → specific
            "가중평균자본비용": [{"page": "WACC 장표", "cell": "B1"}],
            "관리보수": [{"page": "제2호_비용", "cell": "C6"}, {"page": "P2", "cell": "x"},
                      {"page": "P3", "cell": "x"}, {"page": "P4", "cell": "x"},
                      {"page": "P5", "cell": "x"},
                      {"page": "FDD5 — [STELLA] Related Party", "cell": "FDD5"}],  # 6 pages → generic
        },
    }


def _derives(idx, page):
    return [d["page"] for d in (idx["pages"][page].get("derives_from") or [])]


def test_gate0_blocks_different_entity_deck():
    idx = _idx()
    build_cross_refs(idx)
    # STELLA (same entity as the Centroid Excel) links on the specific WACC term
    assert _derives(idx, "FDD17 — [STELLA] DCF Summary") == ["WACC 장표"]
    # CAESAR (Celadon — different company) shares WACC but must NOT link
    assert _derives(idx, "FDD8 — [CAESAR] WACC") == []


def test_generic_term_does_not_link():
    idx = _idx()
    build_cross_refs(idx, k=4)
    # 관리보수 spans 6 pages (> k) → generic category, not an identity → no link
    assert _derives(idx, "FDD5 — [STELLA] Related Party") == []


def test_bipartite_and_directional():
    idx = _idx()
    build_cross_refs(idx)
    # derives_from only on PDF pages; cited_by only on Excel pages
    assert "derives_from" not in idx["pages"]["WACC 장표"]
    assert idx["pages"]["WACC 장표"]["cited_by"] == ["FDD17 — [STELLA] DCF Summary"]
    assert "cited_by" not in idx["pages"]["FDD17 — [STELLA] DCF Summary"]


def test_via_reason_recorded():
    idx = _idx()
    build_cross_refs(idx)
    via = idx["pages"]["FDD17 — [STELLA] DCF Summary"]["derives_from"][0]["via"]
    assert via.startswith("metric:")


def test_idempotent():
    idx = _idx()
    build_cross_refs(idx)
    build_cross_refs(idx)  # second run must not accumulate cited_by
    assert idx["pages"]["WACC 장표"]["cited_by"] == ["FDD17 — [STELLA] DCF Summary"]


def test_lint_flags_bad_cross_refs():
    from src.stella_kb.wiki.lint import _check_cross_refs

    idx = {"pages": {
        "FDD1 — [STELLA] X": {"source": "PDF", "derives_from": [
            {"page": "GHOST", "via": "x"},                 # dangling target
            {"page": "FDD2 — [STELLA] Y", "via": "x"}]},   # PDF→PDF (forbidden)
        "FDD2 — [STELLA] Y": {"source": "PDF"},
        "Excel A": {"cited_by": []},
        "Excel B": {"derives_from": [{"page": "Excel A"}]},  # derives_from on a non-PDF page
    }}
    valid = {"FDD1 — [STELLA] X", "FDD2 — [STELLA] Y", "Excel A", "Excel B"}
    msgs = " | ".join(f["msg"] for f in _check_cross_refs(idx, valid))
    assert "not a real page" in msgs        # GHOST
    assert "PDF↔PDF forbidden" in msgs       # FDD1 → FDD2
    assert "non-PDF page" in msgs            # Excel B has derives_from


def test_llm_judge_only_confirms_candidates():
    idx = _idx()
    seen = []

    def judge(pdf, excel, index):
        seen.append((pdf, excel))
        return excel == "WACC 장표"            # confirm only the WACC pair

    build_cross_refs(idx, judge=judge)
    # judge was called ONLY on the deterministic candidate (whitelist), never a CAESAR/cross pair
    assert seen == [("FDD17 — [STELLA] DCF Summary", "WACC 장표")]
    assert _derives(idx, "FDD17 — [STELLA] DCF Summary") == ["WACC 장표"]
    assert idx["pages"]["FDD17 — [STELLA] DCF Summary"]["derives_from"][0]["via"].startswith("llm:")
