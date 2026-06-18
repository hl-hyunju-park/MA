"""Alias-index dedup — structural stopword removal + same-cell reorder collapse. Offline."""

from __future__ import annotations

from src.stella_kb.wiki.dedup import _token_set, analyze, dedup_alias_index


def _idx() -> dict:
    return {
        "pages": {
            "BS": {"aliases": ["유동자산", "Total Assets", "Accounts Receivable Gross",
                               "Gross Accounts Receivable", "관리보수", "관리보수율", "Balance Check"]},
        },
        "alias_index": {
            # legitimate metrics — kept
            "유동자산": [{"page": "BS", "cell": "B5", "term": "유동자산"}],
            "관리보수": [{"page": "BS", "cell": "B6", "term": "관리보수"},
                       {"page": "PL", "cell": "C6", "term": "관리보수"}],
            "관리보수율": [{"page": "BS", "cell": "B7", "term": "관리보수율"}],  # distinct from 관리보수
            # structural stopwords — removed
            "totalassets": [{"page": "BS", "cell": "B20", "term": "Total Assets"}],
            "합계": [{"page": "BS", "cell": "B21", "term": "합계"},
                    {"page": "PL", "cell": "C21", "term": "합계"}],
            "balancecheck": [{"page": "BS", "cell": "B99", "term": "Balance Check"}],
            # pure reorder of the SAME cell (B8) — collapse to one canonical
            "accountsreceivablegross": [{"page": "BS", "cell": "B8", "term": "Accounts Receivable Gross"}],
            "grossaccountsreceivable": [{"page": "BS", "cell": "B8", "term": "Gross Accounts Receivable"}],
        },
    }


def test_token_set_is_order_insensitive():
    assert _token_set("Accounts Receivable Gross") == _token_set("Gross Accounts Receivable")
    assert _token_set("관리보수") != _token_set("관리보수율")  # distinct → never collapsed


def test_structural_stopwords_removed_metrics_kept():
    idx = _idx()
    dedup_alias_index(idx)
    ai = idx["alias_index"]
    for noise in ("totalassets", "합계", "balancecheck"):
        assert noise not in ai
    for keep in ("유동자산", "관리보수", "관리보수율"):
        assert keep in ai            # real metrics survive even when they overlap pages


def test_same_cell_reorder_collapses_to_one():
    idx = _idx()
    dedup_alias_index(idx)
    ai = idx["alias_index"]
    present = [k for k in ("accountsreceivablegross", "grossaccountsreceivable") if k in ai]
    assert present == ["accountsreceivablegross"]  # canonical (sorted-first) kept, other dropped


def test_page_aliases_kept_consistent_with_index():
    idx = _idx()
    dedup_alias_index(idx)
    from src.stella_kb.wiki.dedup import _norm
    valid = set(idx["alias_index"])
    aliases = idx["pages"]["BS"]["aliases"]
    assert all(_norm(a) in valid for a in aliases)   # no page alias points at a removed key
    assert "Total Assets" not in aliases and "Balance Check" not in aliases
    assert "유동자산" in aliases and "관리보수" in aliases


def test_report_and_idempotent():
    idx = _idx()
    rep = dedup_alias_index(idx)
    assert rep["stopword_terms_removed"] and rep["reorder_hits_collapsed"] == 1
    # second run is a no-op
    rep2 = dedup_alias_index(idx)
    assert not rep2["stopword_terms_removed"] and rep2["reorder_hits_collapsed"] == 0


def test_analyze_counts_overlap():
    a = analyze(_idx())
    assert a["alias_terms"] == 8 and a["max_pages"] == 2  # 관리보수/합계 hit 2 pages
