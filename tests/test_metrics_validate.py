"""Validate the hand-curated metric anchors against the real workbook (skips if it's absent).

`graph/metrics.py` hardcodes cell refs (K59, per-fund rows, the MGT exhibit cells). This guards that
table against silent drift: every anchor must resolve to a present, numeric/date cell. Gated on the
`full_workbook` fixture (conftest skips when the workbook isn't checked out), so a fresh checkout
stays green. This is the v0.1 graph paradigm — independent of the v0.3 data-room path.
"""

from __future__ import annotations

from src.stella_kb.graph import metrics


def test_is_value_accepts_numbers_and_dates_not_bool_or_str():
    import datetime
    assert metrics._is_value(12.5) and metrics._is_value(0)
    assert metrics._is_value(datetime.date(2024, 1, 1))
    assert not metrics._is_value(True)        # bool is not a datum
    assert not metrics._is_value("206,131")   # a string means the anchor drifted
    assert not metrics._is_value(None)


def test_all_metric_anchors_resolve_to_a_value(full_workbook):
    problems = metrics.validate_anchors(full_workbook)
    assert problems == [], "metric anchors drifted:\n" + "\n".join(problems)
