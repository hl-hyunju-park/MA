"""parse_llm axis detection — the deterministic grounding half that turns an LLM-named axis row
into a {column: period} map. These pin the fiscal-label recognition (``_year_at``) and the
largest-contiguous-run isolation (``_axis_columns``), offline (no LLM, no workbook).

Regression focus: Korean ``YYYY년`` / ``YYYY년 N월`` headers. ``\\b(20\\d\\d)\\b`` silently missed
them (년 is a word char, so no boundary after the digits), which dropped whole tables — e.g.
임직원 수's 연도별 재직인원수 axis collapsed to the monthly roster's lone overlapping 2021 column.
"""

from __future__ import annotations

from src.stella_kb.wiki.parse_llm import _axis_columns, _year_at


def test_year_at_recognizes_korean_year_headers():
    assert _year_at("2019년") == 2019
    assert _year_at("2020년") == 2020
    assert _year_at("2024년 8월") == "8M24"   # interim month → distinct label, not annual 2024


def test_year_at_keeps_existing_formats():
    assert _year_at("2024") == 2024
    assert _year_at("FY24") == 2024
    assert _year_at("Dec-20") == 2020
    assert _year_at("6M 24") == "6M24"
    assert _year_at("1H24") == "1H24"
    assert _year_at("T.V.") == "T.V."
    assert _year_at("random text") is None


def test_year_at_rejects_longer_numbers():
    # the non-digit-neighbour guard must not match a year *inside* a longer number
    assert _year_at("20241") is None
    assert _year_at("120200") is None


def test_axis_columns_picks_korean_year_run_over_monthly_overlap():
    """Row 72 of 임직원 수: B–G are the 연도별 재직인원수 headers; V/W are the monthly roster's
    overlapping cells. The largest contiguous run (B–G = 6) must win over the 2-col overlap."""
    vals = {
        "A72": "구분(단위: 명)", "B72": "2019년", "C72": "2020년", "D72": "2021년",
        "E72": "2022년", "F72": "2023년", "G72": "2024년 8월",
        "V72": "2021", "W72": 2021, "X72": 1,  # monthly-roster overlap on the same row
    }
    cols = _axis_columns(72, vals)
    assert cols == {"B": 2019, "C": 2020, "D": 2021, "E": 2022, "F": 2023, "G": "8M24"}
    assert len({str(p) for p in cols.values()}) >= 2  # ≥2 periods → table is kept, not dropped
