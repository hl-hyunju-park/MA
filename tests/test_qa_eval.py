"""Offline unit tests for the qa_eval reporting helpers (no LLM judge run).

The full `judge()` run is live-LLM; here we pin only the dispersion reporting added to make the
noisy eval honest — `_stdev` (population σ) and the `mean ± σ` breakdown table.
"""

from __future__ import annotations

from eval import qa_eval


def test_stdev_population_and_degenerate():
    assert qa_eval._stdev([1, 1, 1]) == 0.0          # no spread
    assert qa_eval._stdev([0, 1]) == 0.5             # population σ, not sample
    assert qa_eval._stdev([]) == 0.0                 # n<2 guarded
    assert qa_eval._stdev([0.7]) == 0.0


def test_breakdown_table_reports_mean_and_sigma():
    scores = [{"doc": "CAESAR", "score": 1.0}, {"doc": "CAESAR", "score": 0.0},
              {"doc": "LIFE", "score": 0.5}]
    rows = qa_eval._breakdown_table("doc별", "doc", scores)
    assert "| 그룹 | n | mean ± σ |" in rows
    # CAESAR: mean 0.50 ± 0.50 (n=2); LIFE: 0.50 ± 0.00 (n=1)
    assert any("CAESAR | 2 | 0.50 ± 0.50" in r for r in rows)
    assert any("LIFE | 1 | 0.50 ± 0.00" in r for r in rows)
