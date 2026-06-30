"""Supervisor hub-and-spoke StateGraph — tested deterministically (offline, no LLM / no network).

The supervisor decides via a JSON completion (``supervisor.chat``) and hands off to the wiki/dart
research spokes, then to the synthesizer (``finalize``). Here ``chat`` is scripted, the spokes
(``core.aresearch`` / ``dart._arun``) and the wiki synthesizer (``wiki.synthesize.synthesize`` /
``synthesize_stream``) are stubbed, so we drive the *real compiled graph* and assert handoff
routing, research-then-synthesize, dart-only passthrough, trace/source bookkeeping, the per-request
``store`` threading, and the fallback path — without touching gemma-4. The live end-to-end run is
the ``__main__`` smoke, not here.
"""

from __future__ import annotations

import asyncio

import apps.agent.cores.wiki.synthesize as wiki_synth
from apps.agent.cores import supervisor


# --- pure helpers ----------------------------------------------------------------------


def test_source_gathered_count_tag_renumber_helpers():
    assert supervisor._source_label([{"x": 1}], {"dart": "y"}) == "dart+wiki"
    assert supervisor._source_label([{"x": 1}], {}) == "wiki"
    assert supervisor._source_label([], {"dart": "y"}) == "dart"
    assert supervisor._source_label([], {}) == "none"

    assert supervisor._gathered({"evidence": [{"x": 1}]}) == ["wiki"]
    assert supervisor._gathered({"findings": {"dart": "y"}}) == ["dart"]
    assert supervisor._gathered({"evidence": [1], "findings": {"dart": "y"}}) == ["wiki", "dart"]
    assert supervisor._gathered({}) == []

    trace = [
        {"agent": "supervisor", "action": "call"},
        {"agent": "wiki:planner", "action": "plan"},
        {"agent": "supervisor", "action": "call"},
        {"agent": "supervisor", "action": "result"},
    ]
    assert supervisor._count_calls(trace) == 2

    tagged = supervisor._tag([{"agent": "planner", "action": "plan", "arg": "x", "thought": ""}], "wiki")
    assert tagged[0]["agent"] == "wiki:planner"

    renum = supervisor._renumber([{"agent": "a"}, {"agent": "b"}, {"agent": "c"}])
    assert [e["step"] for e in renum] == [0, 1, 2]

    assert supervisor._chunk("abcdef", size=4) == ["abcd", "ef"]
    assert supervisor._chunk("") == [""]


def test_progress_sig_and_evidence_digest():
    ev = [{"page": "P", "cell": "A1", "term": "AUM", "value": "100"},
          {"page": "P", "cell": "A1", "term": "AUM", "value": "100"},   # dup
          {"page": "P", "cell": "B2", "term": "fee", "value": "5"}]
    sig = supervisor._progress_sig
    assert sig(ev, {}) == sig([ev[0], ev[2]], {})        # dup (page,cell) ignored — no false progress
    assert sig(ev, {}) != sig([ev[0]], {})               # B2 is genuinely new material
    assert sig(ev, {"dart": ""}) == sig(ev, {})          # empty dart answer is NOT progress
    assert sig(ev, {"dart": "x"}) != sig(ev, {})         # a non-empty dart finding IS
    assert sig(ev, {"dart": "짧은"}) != sig(ev, {"dart": "더 긴 답변"})  # richer re-answer ≠ stall

    digest = supervisor._evidence_digest(ev, {"dart": "삼성 매출 300조"})
    assert "AUM = 100" in digest and "A1" in digest      # facts surfaced for the decision
    assert "dart 자료" in digest and "삼성" in digest      # dart findings surfaced too


# --- the decision -----------------------------------------------------------------------


def test_decide_parses_json(monkeypatch):
    monkeypatch.setattr(supervisor, "chat",
                        lambda *a, **k: '{"next":"wiki","query":"엔터프라이즈 밸류","thought":"내부"}')
    d = supervisor._decide("질문", called=[], gathered=[])
    assert d == {"next": "wiki", "query": "엔터프라이즈 밸류", "thought": "내부"}


def test_decide_defaults_to_finish_on_garbage(monkeypatch):
    monkeypatch.setattr(supervisor, "chat", lambda *a, **k: "no json here")
    d = supervisor._decide("원래 질문", called=["wiki"], gathered=["wiki"])
    assert d["next"] == "FINISH"
    assert d["query"] == "원래 질문"          # falls back to the original question


def test_decide_survives_chat_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("endpoint down")
    monkeypatch.setattr(supervisor, "chat", boom)
    assert supervisor._decide("q", [], [])["next"] == "FINISH"


def test_decide_logs_warning_on_chat_error(monkeypatch, caplog):
    # the silent-FINISH degradation must be OBSERVABLE (not mistakable for a real finish)
    def boom(*a, **k):
        raise RuntimeError("endpoint down")
    monkeypatch.setattr(supervisor, "chat", boom)
    import logging
    with caplog.at_level(logging.WARNING, logger="apps.agent.supervisor"):
        out = supervisor._decide("q", [], [])
    assert out["next"] == "FINISH"                       # still degrades gracefully
    assert any("RuntimeError" in r.message and "endpoint down" in r.message
               and "FINISH" in r.message for r in caplog.records)


# --- scripted graph drivers -------------------------------------------------------------

_EVIDENCE = [{"page": "PL", "cell": "J7", "term": "관리수수료", "value": "12,411", "ask": "q"}]


def _script_chat(monkeypatch, decisions: list[str]):
    """Stub ``supervisor.chat`` to hand back queued decision JSON in order (drained → FINISH)."""
    queue = list(decisions)

    def fake(messages, **k):
        return queue.pop(0) if queue else '{"next":"FINISH","query":"","thought":"done"}'
    monkeypatch.setattr(supervisor, "chat", fake)


def _stub_spokes(monkeypatch, evidence=None, dart="다트 답변", seen=None):
    """Stub the research spokes: ``core.aresearch`` (wiki) and ``dart._arun`` (dart)."""
    evidence = _EVIDENCE if evidence is None else evidence

    async def fake_aresearch(q, store=None, **k):
        if seen is not None:
            seen["wiki_q"], seen["store"] = q, store
        return {"evidence": evidence, "paths": [], "caveats": [],
                "trace": [{"agent": "planner", "action": "plan", "arg": "1", "thought": ""}], "steps": 1}

    async def fake_dart(q):
        if seen is not None:
            seen["dart_q"] = q
        return {"answer": dart, "trace": [{"agent": "dart", "action": "call", "arg": "x", "thought": ""}], "steps": 1}

    monkeypatch.setattr("apps.agent.core.aresearch", fake_aresearch)
    monkeypatch.setattr("apps.agent.cores.dart._arun", fake_dart)


def _stub_synth(monkeypatch, text="종합 답변", seen=None):
    """Stub the wiki synthesizer used by the hub finalize node (buffered + streaming)."""
    def fake_synthesize(state):
        if seen is not None:
            seen["synth_state"] = state
        return text, {"agent": "synthesizer", "action": "answer", "arg": "", "thought": ""}

    def fake_stream(state):
        if seen is not None:
            seen["synth_state"] = state
        yield text

    monkeypatch.setattr(wiki_synth, "synthesize", fake_synthesize)
    monkeypatch.setattr(wiki_synth, "synthesize_stream", fake_stream)


def test_single_wiki_synthesizes(monkeypatch):
    # supervisor hands off wiki → FINISH → synthesizer composes over the wiki evidence.
    _script_chat(monkeypatch, ['{"next":"wiki","query":"q1","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    seen = {}
    _stub_spokes(monkeypatch, seen=seen)
    _stub_synth(monkeypatch, text="센트로이드 EV는 1206억", seen=seen)

    out = supervisor.run_supervised("센트로이드 기업가치?")
    assert out["source"] == "wiki"
    assert out["answer"] == "센트로이드 EV는 1206억"          # synthesizer output
    assert out["steps"] == 1                                  # one spoke dispatch
    assert seen["wiki_q"] == "q1"                             # the supervisor's tailored sub-query
    assert out["evidence"] == _EVIDENCE
    assert seen["synth_state"]["evidence"] == _EVIDENCE       # synthesizer saw the gathered evidence
    assert any(e["agent"] == "wiki:planner" for e in out["trace"])   # spoke trace namespaced
    assert out["trace"][-1]["agent"] == "synthesizer"
    assert [e["step"] for e in out["trace"]] == list(range(len(out["trace"])))


def test_composite_two_sources_synthesize(monkeypatch):
    # wiki → dart → FINISH → ONE synthesis over evidence + dart findings (no double-synthesis).
    _script_chat(monkeypatch, ['{"next":"wiki","query":"센트로이드","thought":"t"}',
                               '{"next":"dart","query":"삼성전자","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    seen = {}
    _stub_spokes(monkeypatch, dart="삼성전자 매출 300조", seen=seen)
    _stub_synth(monkeypatch, text="센트로이드와 삼성전자 비교 종합", seen=seen)

    out = supervisor.run_supervised("센트로이드와 삼성전자 비교")
    assert out["source"] == "dart+wiki"
    assert out["answer"] == "센트로이드와 삼성전자 비교 종합"
    assert out["steps"] == 2
    assert seen["dart_q"] == "삼성전자"
    assert seen["synth_state"]["findings"] == {"dart": "삼성전자 매출 300조"}  # findings reached the synthesizer


def test_dart_failure_becomes_finding_keeps_wiki_evidence(monkeypatch):
    # a DART outage on a composite question must NOT raise out of the graph and discard the wiki
    # evidence already gathered — arun_safe turns it into an error finding the synthesizer folds in.
    _script_chat(monkeypatch, ['{"next":"wiki","query":"센트로이드","thought":"t"}',
                               '{"next":"dart","query":"삼성전자","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])

    async def fake_aresearch(q, store=None, **k):
        return {"evidence": _EVIDENCE, "paths": [], "caveats": [],
                "trace": [{"agent": "planner", "action": "plan", "arg": "1", "thought": ""}], "steps": 1}

    async def boom_dart(q):
        raise RuntimeError("DART 서버 다운")

    monkeypatch.setattr("apps.agent.core.aresearch", fake_aresearch)
    monkeypatch.setattr("apps.agent.cores.dart._arun", boom_dart)   # arun_safe wraps this
    seen = {}
    _stub_synth(monkeypatch, text="위키 기반 답변", seen=seen)

    out = supervisor.run_supervised("센트로이드와 삼성전자 비교")
    assert out["answer"] == "위키 기반 답변"             # synthesized, not a crash/empty fallback
    assert out["evidence"] == _EVIDENCE                  # wiki evidence preserved despite the DART failure
    assert "DART" in seen["synth_state"]["findings"]["dart"]   # the error surfaced as a finding
    assert out["source"] == "dart+wiki"


def test_max_steps_threads_to_wiki_spoke(monkeypatch):
    # core.answer(source="auto", max_steps=N) must reach the wiki research spoke (was silently dropped).
    _script_chat(monkeypatch, ['{"next":"wiki","query":"q","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    seen = {}

    async def fake_aresearch(q, store=None, max_steps=None, **k):
        seen["max_steps"] = max_steps
        return {"evidence": _EVIDENCE, "paths": [], "caveats": [], "trace": [], "steps": 1}

    monkeypatch.setattr("apps.agent.core.aresearch", fake_aresearch)
    _stub_synth(monkeypatch, text="x")

    supervisor.run_supervised("질문", max_steps=7)
    assert seen["max_steps"] == 7                         # threaded run_supervised → _make_wiki_node → aresearch


def test_dart_only_passthrough(monkeypatch):
    # dart → FINISH, no wiki evidence → DART's cited answer is passed through verbatim (not re-prosed).
    _script_chat(monkeypatch, ['{"next":"dart","query":"삼성전자","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    _stub_spokes(monkeypatch, dart="삼성전자 매출 300조")

    out = supervisor.run_supervised("삼성전자 매출?")
    assert out["source"] == "dart"
    assert out["answer"] == "삼성전자 매출 300조"
    assert out["trace"][-1]["action"] == "passthrough"


def test_supervisor_redispatches_on_gap_then_stalls(monkeypatch):
    # evidence-aware gate: the supervisor keeps asking wiki to fill a gap; the FIRST call finds
    # evidence, later calls find nothing → the no-progress guard finalizes over what we have
    # (re-dispatch happens, but it can't loop forever).
    _script_chat(monkeypatch, ['{"next":"wiki","query":"지급여력비율","thought":"필요"}',
                               '{"next":"wiki","query":"분기별로 더","thought":"빈틈"}',
                               '{"next":"wiki","query":"또 더","thought":"빈틈"}'])  # 3rd never reached
    calls = {"n": 0}

    async def fake_aresearch(q, store=None, **k):
        calls["n"] += 1
        ev = _EVIDENCE if calls["n"] == 1 else []        # first call finds; re-dispatch finds nothing
        return {"evidence": ev, "paths": [], "caveats": [],
                "trace": [{"agent": "planner", "action": "plan", "arg": "1", "thought": ""}], "steps": 1}

    monkeypatch.setattr("apps.agent.core.aresearch", fake_aresearch)
    monkeypatch.setattr("apps.agent.cores.dart._arun", lambda q: None)
    _stub_synth(monkeypatch, text="정체 후 종합")

    out = supervisor.run_supervised("KDB생명 지급여력비율?")
    assert out["source"] == "wiki"
    assert out["answer"] == "정체 후 종합"
    assert calls["n"] == 2                                # re-dispatched once, then stalled → finalize
    assert any(e.get("thought", "").startswith("정체") for e in out["trace"])  # stall-stop recorded


def test_grounds_when_supervisor_finishes_empty(monkeypatch):
    # supervisor says FINISH before calling anything → must still ground via the wiki, not finish empty.
    _script_chat(monkeypatch, ['{"next":"FINISH","query":"","thought":"몰라"}'])
    _stub_spokes(monkeypatch)
    _stub_synth(monkeypatch, text="그래도 위키 답변")

    out = supervisor.run_supervised("애매한 질문")
    assert out["source"] == "wiki"
    assert out["answer"] == "그래도 위키 답변"


def test_graph_failure_falls_back_to_route(monkeypatch):
    def boom(*_a):
        raise RuntimeError("graph build boom")
    monkeypatch.setattr(supervisor, "_build_supervisor", boom)
    monkeypatch.setattr("apps.agent.core.route", lambda q: "dart")

    async def fake_dart(q):
        return {"answer": "다트 폴백", "trace": [], "steps": 1}
    monkeypatch.setattr("apps.agent.cores.dart._arun", fake_dart)

    out = supervisor.run_supervised("삼성전자 매출?")
    assert out["source"] == "dart"
    assert out["answer"] == "다트 폴백"


# --- streaming --------------------------------------------------------------------------


def _drain(agen):
    async def collect():
        return [ev async for ev in agen]
    return asyncio.run(collect())


def test_stream_synthesizes_real_tokens(monkeypatch):
    # wiki-only via the supervisor graph → research steps, then the synthesizer's REAL tokens.
    _script_chat(monkeypatch, ['{"next":"wiki","query":"q1","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    _stub_spokes(monkeypatch)
    _stub_synth(monkeypatch, text="센트로이드 EV 1206억")

    evs = _drain(supervisor.astream_supervised("센트로이드 기업가치?"))
    types = [e["type"] for e in evs]
    assert "step" in types and "token" in types and types[-1] == "answer"
    assert "".join(e["text"] for e in evs if e["type"] == "token") == "센트로이드 EV 1206억"
    assert evs[-1]["answer"] == "센트로이드 EV 1206억"


def test_stream_dart_only_replays_tokens(monkeypatch):
    # dart-only → the verbatim cited answer is chunk-replayed as tokens (dart doesn't token-stream).
    _script_chat(monkeypatch, ['{"next":"dart","query":"삼성전자","thought":"t"}',
                               '{"next":"FINISH","query":"","thought":"done"}'])
    _stub_spokes(monkeypatch, dart="삼성전자 매출 300조")

    evs = _drain(supervisor.astream_supervised("삼성전자 매출?"))
    types = [e["type"] for e in evs]
    assert "step" in types and types[-1] == "answer"
    assert evs[-1]["answer"] == "삼성전자 매출 300조"


# --- nodes in isolation -----------------------------------------------------------------


def test_synthesis_plan_is_single_decision():
    # one source of truth for buffered finalize + streaming tail (no drift)
    p = supervisor._synthesis_plan({"question": "q", "evidence": _EVIDENCE, "findings": {"dart": "d"}})
    assert p["mode"] == "synthesize" and p["source"] == "dart+wiki"
    assert p["synth_state"]["evidence"] == _EVIDENCE and p["synth_state"]["findings"] == {"dart": "d"}

    p2 = supervisor._synthesis_plan({"question": "q", "evidence": [], "findings": {"dart": "삼성 매출"}})
    assert p2["mode"] == "passthrough" and p2["source"] == "dart" and p2["text"] == "삼성 매출"

    p3 = supervisor._synthesis_plan({"question": "q", "evidence": [], "findings": {}})
    assert p3 == {"mode": "none", "source": "none", "synth_state": None, "text": ""}


def test_findings_rendering_and_labels_are_generic():
    # #9: a non-dart spoke must NOT be silently dropped — findings render per source, generically.
    from apps.agent.cores.wiki.synthesize import _synth_user
    base = {"question": "q", "evidence": [], "paths": [], "caveats": []}
    txt = _synth_user({**base, "findings": {"news": "속보 내용"}})
    assert "[news]" in txt and "속보 내용" in txt                 # unknown source rendered under its key
    assert "DART 공시 자료(상장사)" in _synth_user({**base, "findings": {"dart": "삼성"}})  # known label kept

    # supervisor helpers generalize to any non-empty findings source
    assert supervisor._source_label([], {"news": "x", "dart": "y"}) == "dart+news"
    assert supervisor._gathered({"findings": {"news": "x", "blank": ""}}) == ["news"]
    # a single non-wiki source (any name) → passthrough with that source label
    p = supervisor._synthesis_plan({"question": "q", "evidence": [], "findings": {"news": "속보"}})
    assert p["mode"] == "passthrough" and p["source"] == "news" and p["text"] == "속보"


def test_finalize_node_synthesize_vs_passthrough(monkeypatch):
    _stub_synth(monkeypatch, text="종합")
    synth = asyncio.run(supervisor._finalize_node({"question": "q", "evidence": _EVIDENCE, "findings": {}}))
    assert synth["answer"] == "종합" and synth["source"] == "wiki"
    assert synth["trace"][0]["agent"] == "synthesizer" and synth["trace"][0]["action"] == "answer"

    dart_only = asyncio.run(supervisor._finalize_node({"question": "q", "evidence": [], "findings": {"dart": "다트"}}))
    assert dart_only == {"answer": "다트", "source": "dart",
                         "trace": [{"agent": "synthesizer", "action": "passthrough", "arg": "dart", "thought": ""}]}

    empty = asyncio.run(supervisor._finalize_node({"question": "q", "evidence": [], "findings": {}}))
    assert empty == {"answer": "", "source": "none"}


def test_arun_safe_never_raises(monkeypatch):
    import apps.agent.cores.dart as dart

    async def boom(q):
        raise RuntimeError("MCP down")
    monkeypatch.setattr(dart, "_arun", boom)
    out = asyncio.run(dart.arun_safe("q"))
    assert "MCP down" in out["answer"] and out["trace"] == [] and out["steps"] == 0


def test_wiki_node_threads_store_and_returns_evidence(monkeypatch):
    seen = {}
    _stub_spokes(monkeypatch, seen=seen)
    cmd = asyncio.run(supervisor._make_wiki_node("STORE_SENTINEL")({"question": "q", "next_query": "tailored"}))

    assert seen["store"] == "STORE_SENTINEL"      # the per-request store reached the spoke
    assert seen["wiki_q"] == "tailored"           # the supervisor's sub-query, not the raw question
    assert cmd.goto == "supervisor"
    assert cmd.update["evidence"] == _EVIDENCE
    assert "answers" not in cmd.update            # wiki spoke contributes evidence, not an answer
    assert cmd.update["called"] == ["wiki"]
    assert cmd.update["trace"][0]["agent"] == "wiki:planner"
    assert cmd.update["trace"][-1]["action"] == "result"
