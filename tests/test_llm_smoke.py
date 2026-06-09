"""End-to-end smoke tests against the live shared vLLM. Opt-in: ``pytest --run-llm``.

These assert on structure (the right page/cell is cited, the expected agents ran, fan-out
actually produced parallel branches) rather than exact wording, which varies by model run.
"""

from __future__ import annotations

import pytest

from apps.agent.core import run

pytestmark = pytest.mark.llm


def test_mgt_ev_cites_dcf_exhibit():
    r = run("MGT 케이스 enterprise value는 얼마인가?")
    assert "DCF 장표 #1_MGT" in r["answer"]
    agents = {e["agent"] for e in r["trace"]}
    assert {"planner", "router", "retriever", "verifier", "synthesizer"} <= agents
    assert [e["step"] for e in r["trace"]] == list(range(len(r["trace"])))  # renumbered


def test_comparison_fans_out_to_parallel_branches():
    r = run("MGT와 DTT 케이스의 equity value를 비교하면?")
    # the planner should split this; each sub-question runs as its own branch (distinct sub)
    branch_subs = {e["sub"] for e in r["trace"] if 0 <= e.get("sub", -1) < 10**9}
    assert len(branch_subs) >= 2, "comparison should fan out into >= 2 solve branches"
