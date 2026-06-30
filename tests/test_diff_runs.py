"""eval.diff_runs — the regression debugger that joins two eval runs and explains score moves.

Deterministic + offline: builds two synthetic run dirs (answers.json + scores.json) on tmp_path
and asserts the diff isolates the regressed/improved items and the page/evidence/path deltas. No
vLLM, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval import diff_runs


def _write_run(d: Path, scores: list, answers: list) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "scores.json").write_text(json.dumps(scores), encoding="utf-8")
    (d / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    return d


def test_diff_isolates_regression_and_improvement(tmp_path):
    a = _write_run(
        tmp_path / "A",
        scores=[{"id": "Q1", "score": 1.0, "verdict": "correct", "doc": "X", "capability": "C3"},
                {"id": "Q2", "score": 0.0, "verdict": "incorrect", "doc": "X", "capability": "C3"},
                {"id": "Q3", "score": 0.5, "verdict": "partial", "doc": "X", "capability": "C4"}],
        answers=[{"id": "Q1", "pages_opened": ["P1"],
                  "evidence": [{"page": "P1", "cell": "A1", "term": "x", "value": "10"}],
                  "router_paths": ["routes.yaml 직결"]},
                 {"id": "Q2", "pages_opened": ["P2"], "evidence": [], "router_paths": []},
                 {"id": "Q3", "pages_opened": ["P3"], "evidence": [], "router_paths": []}],
    )
    b = _write_run(
        tmp_path / "B",
        scores=[{"id": "Q1", "score": 0.0, "verdict": "incorrect", "doc": "X", "capability": "C3"},
                {"id": "Q2", "score": 1.0, "verdict": "correct", "doc": "X", "capability": "C3"},
                {"id": "Q3", "score": 0.5, "verdict": "partial", "doc": "X", "capability": "C4"}],
        answers=[{"id": "Q1", "pages_opened": ["P9"], "evidence": [], "router_paths": ["router"]},
                 {"id": "Q2", "pages_opened": ["P2"],
                  "evidence": [{"page": "P2", "cell": "B2", "term": "y", "value": "20"}],
                  "router_paths": []},
                 {"id": "Q3", "pages_opened": ["P3"], "evidence": [], "router_paths": []}],
    )

    result = diff_runs.diff(a, b)

    assert result["shared"] == 3
    assert [it["id"] for it in result["regressed"]] == ["Q1"]
    assert [it["id"] for it in result["improved"]] == ["Q2"]

    q1 = next(it for it in result["items"] if it["id"] == "Q1")
    assert q1["delta"] == -1.0
    assert q1["pages_removed"] == ["P1"] and q1["pages_added"] == ["P9"]
    # the evidence row the synthesizer LOST on the regression is surfaced verbatim
    assert any("A1" in e and "x=10" in e for e in q1["evidence_removed"])
    assert q1["evidence_added"] == []

    q2 = next(it for it in result["items"] if it["id"] == "Q2")
    assert q2["delta"] == 1.0
    assert any("B2" in e and "y=20" in e for e in q2["evidence_added"])


def test_missing_fields_degrade_not_crash(tmp_path):
    """A run that predates the evidence/router_paths fields still diffs on score + pages."""
    a = _write_run(
        tmp_path / "A",
        scores=[{"id": "Q1", "score": 1.0, "verdict": "correct"}],
        answers=[{"id": "Q1", "pages_opened": ["P1"]}],  # no evidence / router_paths keys
    )
    b = _write_run(
        tmp_path / "B",
        scores=[{"id": "Q1", "score": 0.0, "verdict": "incorrect"}],
        answers=[{"id": "Q1", "pages_opened": ["P1"]}],
    )
    result = diff_runs.diff(a, b)
    assert len(result["regressed"]) == 1
    # render must not raise on the degraded (field-less) records
    out = diff_runs.render(result, a, b)
    assert "Regressed" in out and "Q1" in out


def test_absent_run_dir_is_empty_not_error(tmp_path):
    """A nonexistent dir loads as empty (no shared items) rather than raising."""
    a = _write_run(tmp_path / "A", scores=[{"id": "Q1", "score": 1.0}], answers=[{"id": "Q1"}])
    result = diff_runs.diff(a, tmp_path / "does_not_exist")
    assert result["shared"] == 0 and result["only_a"] == ["Q1"]


def test_noise_floor_buckets_small_deltas(tmp_path):
    """A small move (+0.05) is within-noise at the default floor but real at a tighter floor; a big
    move (+0.5) is always improved."""
    a = _write_run(
        tmp_path / "A",
        scores=[{"id": "Q1", "score": 0.50}, {"id": "Q2", "score": 0.50}],
        answers=[{"id": "Q1", "pages_opened": []}, {"id": "Q2", "pages_opened": []}],
    )
    b = _write_run(
        tmp_path / "B",
        scores=[{"id": "Q1", "score": 0.55}, {"id": "Q2", "score": 1.00}],   # +0.05 noise, +0.50 real
        answers=[{"id": "Q1", "pages_opened": []}, {"id": "Q2", "pages_opened": []}],
    )

    res = diff_runs.diff(a, b)                                  # default noise_floor = 0.1
    assert [it["id"] for it in res["improved"]] == ["Q2"]       # only the +0.50 counts as signal
    assert [it["id"] for it in res["within_noise"]] == ["Q1"]   # +0.05 parked as noise
    assert "Within noise" in diff_runs.render(res, a, b)

    tight = diff_runs.diff(a, b, noise_floor=0.01)              # tighten → +0.05 now counts
    assert {it["id"] for it in tight["improved"]} == {"Q1", "Q2"}
    assert tight["within_noise"] == []
