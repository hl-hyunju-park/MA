"""Supervisor-centric **hub-and-spoke** agent — a central supervisor that decides each handoff
among cohesive *specialist* agents (spokes), then hands off to the **synthesizer** for the final
answer. A real LangGraph ``StateGraph``; spokes route control back to the supervisor via
``Command(goto="supervisor")``::

            ┌──────────────┐
   START →  │  SUPERVISOR  │  ── decides handoff each turn ──┐
            └──────────────┘  ◀── spokes hand control back ──┘
                 │   │   │
   ┌─────────────┘   │   └──────────────┐
   ▼                 ▼                  ▼
 wiki (research)   dart (research)   finalize ─→ END
 returns EVIDENCE  returns FINDINGS  (synthesizer: one cited
 (planner→route→   (tool-calling)     answer over ALL gathered
  retrieve→verify;                    evidence + findings)
  fan-out inside)

Key differences from the old two-backend router:
  - **Synthesis is a hub spoke, not buried in the wiki worker.** The wiki spoke now does
    *research only* (``core.aresearch`` — planner→router→retriever→verifier, fan-out preserved,
    returns cell-anchored evidence); the **supervisor** owns the final answer by handing off to
    the synthesizer, which composes once over the combined wiki evidence + DART findings. No more
    double-synthesis on composite questions.
  - **Real streaming.** ``finalize`` is a graph node for the buffered path; the SSE path drives the
    graph for the research/decision ``step`` events, then streams the synthesizer's *real* tokens
    (``synthesize_stream``) outside the graph — so the answer streams token-by-token for **every**
    auto question, composite included (the old buffered path replayed a finished answer as fake
    chunks). Trade-off: a pure-wiki question now pays the supervisor's two decision calls before the
    first token — slower-to-first-token than the deleted ``route()=="wiki"`` fast-path, the cost of
    routing all auto traffic through the central supervisor (a deterministic first hop could restore
    it later).
  - **Re-routing is first-class.** The supervisor sees each spoke's result and can call the other
    spoke (composite) or finish — real orchestration, not one shot.

The supervisor *decides* with a plain JSON completion (stdlib :func:`chat` + ``parse_action``) — no
tool-calling, more robust on the gemma-4 we serve. Per-request
:class:`apps.agent.utils.datasets.WikiStore` (``store``) is closed over by the wiki spoke, so
concurrency safety holds. On any failure the whole thing degrades to ``core.route`` + direct
dispatch, so a flaky round never hard-fails a request.

Config (env), shared with ``dart``:
    STELLA_TOOL_LLM_URL / STELLA_TOOL_LLM_MODEL   (unused here — kept for the dart spoke)
"""

from __future__ import annotations

import asyncio
import logging
import operator
from typing import Annotated, Any

from langgraph.graph import END, MessagesState, START, StateGraph

from src.stella_kb.llm import chat

from .wiki.nodes import parse_action
from ..prompts import load as load_prompt

log = logging.getLogger("apps.agent.supervisor")

_MAX_TURNS = 5  # supervisor visits before we force a finish (initial + re-dispatch slack)


# --- state ------------------------------------------------------------------------------


def _merge(a: dict, b: dict) -> dict:
    """Reducer for the ``findings`` channel: later spoke writes win on a key collision (none
    expected — each spoke writes its own key)."""
    return {**(a or {}), **(b or {})}


class SupervisorState(MessagesState, total=False):
    """State threaded through the supervisor graph. Subclasses ``MessagesState`` for the standard
    ``messages`` channel. The ``operator.add`` / ``_merge`` channels accumulate across the
    supervisor↔spoke loop; ``turns``/``next_query`` are last-write. The synthesizer composes over
    the gathered research: ``evidence`` (wiki, cell-anchored) + ``findings`` (dart prose), with
    ``paths``/``caveats`` carried for the wiki synthesizer's provenance + audit blocks."""

    question: str  # the user question
    next_query: str  # sub-question the supervisor sent to the routed spoke
    evidence: Annotated[list, operator.add]  # wiki spoke's cell-anchored facts (RAGAS contexts)
    paths: Annotated[list, operator.add]  # wiki provenance chains [{ask, direction, chain}]
    caveats: Annotated[list, operator.add]  # wiki auditor's cross-evidence red flags
    findings: Annotated[dict, _merge]  # {source: prose} from non-wiki spokes ({"dart": ...})
    called: Annotated[list, operator.add]  # spoke names already run (for the decision + guard)
    trace: Annotated[list, operator.add]  # step records [{agent, action, arg, thought}]
    turns: int  # supervisor invocation count (loop guard)
    last_sig: str  # signature of the distinct material gathered (evidence cells + findings content)
                   # at the previous supervisor visit — the no-progress detector: a re-dispatch that
                   # adds nothing NEW → finalize
    answer: str  # final answer (synthesizer / finalize node)
    source: str  # final source label: wiki | dart | dart+wiki | none


# --- trace helpers ----------------------------------------------------------------------


def _tag(trace: list[dict], source: str) -> list[dict]:
    """Namespace a spoke's trace entries (``planner`` → ``"wiki:planner"`` etc.), order kept."""
    out = []
    for e in trace:
        e = dict(e)
        e["agent"] = f"{source}:{e.get('agent', '')}".rstrip(":")
        out.append(e)
    return out


def _renumber(trace: list[dict]) -> list[dict]:
    """Assign a sequential global ``step`` over the merged (execution-ordered) trace."""
    out = []
    for i, e in enumerate(trace):
        e = dict(e)
        e["step"] = i
        out.append(e)
    return out


def _count_calls(trace: list[dict]) -> int:
    """How many spoke dispatches the supervisor made (the 'work' metric)."""
    return sum(1 for e in trace if e.get("agent") == "supervisor" and e.get("action") == "call")


def _gathered(state: SupervisorState) -> list[str]:
    """Which spokes have actually produced material: wiki (evidence) + any non-empty findings
    source (dart today; generic so a new spoke isn't special-cased)."""
    out = ["wiki"] if state.get("evidence") else []
    out += [src for src, txt in (state.get("findings") or {}).items() if txt]
    return out


def _source_label(evidence: list, findings: dict) -> str:
    """Final source label from what was gathered, e.g. ``"wiki"`` | ``"dart"`` | ``"dart+wiki"``
    (any non-empty findings source contributes — not just dart)."""
    srcs = (["wiki"] if evidence else []) + [src for src, txt in (findings or {}).items() if txt]
    return "+".join(sorted(srcs)) if srcs else "none"


def _progress_sig(evidence: list, findings: dict) -> str:
    """A signature of the *distinct* material gathered — unique evidence cells + each **non-empty**
    findings source's **content** — so the stall guard fires only when a re-dispatch added nothing
    NEW. Deduping evidence by (page, cell) ignores a re-fetch of the same cells; keying findings by
    content (not mere presence) means an empty dart answer is not 'progress' and a richer dart
    re-answer IS (it won't be misread as a stall and cut off). A stable string so it survives a
    future checkpointer."""
    cells = sorted({f"{e.get('page', '')}!{e.get('cell', '')}" for e in (evidence or [])})
    finds = sorted(f"{k}={v}" for k, v in (findings or {}).items() if v)
    return repr((cells, finds))


def _evidence_digest(evidence: list, findings: dict, cap: int = 8) -> str:
    """A compact summary of what's been gathered, fed to the supervisor's decision so it judges
    sufficiency on **substance** (the actual facts + a gap view), not just which spokes ran."""
    lines = [f"- {e.get('term', '')} = {e.get('value', '')} "
             f"({e.get('cell', '')} · {e.get('page', '')})" for e in (evidence or [])[:cap]]
    if len(evidence or []) > cap:
        lines.append(f"- (+{len(evidence) - cap} more wiki facts)")
    wiki_block = "[wiki 근거 %d건]\n%s" % (len(evidence or []), "\n".join(lines) or "  (없음)")
    finds_block = ""
    for src, txt in (findings or {}).items():       # every non-wiki spoke's findings (not just dart)
        if txt:
            finds_block += f"\n[{src} 자료]\n" + (txt[:300] + "…" if len(txt) > 300 else txt)
    return wiki_block + finds_block


def _synth_state(state: SupervisorState) -> dict:
    """Shape the gathered research into the wiki ``AgentState`` the synthesizer expects."""
    return {
        "question": state["question"],
        "evidence": state.get("evidence", []),
        "paths": state.get("paths", []),
        "caveats": state.get("caveats", []),
        "findings": state.get("findings", {}) or {},
    }


def _synthesis_plan(state: SupervisorState) -> dict:
    """The **single** decision for how gathered research becomes the final answer — consumed by both
    the buffered ``finalize`` node and the streaming tail so they cannot drift. Returns
    ``{mode, source, synth_state, text}`` where ``mode`` is:

    - ``"synthesize"`` — wiki evidence present (wiki-only or composite), or ≥2 non-wiki sources: one
      central synthesis over ``synth_state`` (evidence + provenance + caveats + all findings).
    - ``"passthrough"`` — exactly one non-wiki spoke and no wiki evidence: keep that spoke's
      already-cited prose (``text``) verbatim (don't re-prose). Generic — not dart-specific.
    - ``"none"`` — nothing gathered (the caller grounds via the wiki).
    """
    evidence = state.get("evidence", [])
    findings = {src: txt for src, txt in (state.get("findings", {}) or {}).items() if txt}
    if evidence or len(findings) >= 2:
        return {"mode": "synthesize", "source": _source_label(evidence, findings),
                "synth_state": _synth_state(state), "text": ""}
    if len(findings) == 1:
        (src, txt), = findings.items()
        return {"mode": "passthrough", "source": src, "synth_state": None, "text": txt}
    return {"mode": "none", "source": "none", "synth_state": None, "text": ""}


# --- the decision (supervisor node's brain) ---------------------------------------------


_DECISION_DIRECTIVE = (
    "아래 '수집 요약'을 보고, 질문에 **완전히** 답하기 충분한지 판단한 뒤 행동 하나를 JSON으로 출력하세요.\n"
    '- 부족하면(빠진 수치·기간·항목·교차검증 등) 그 빈틈을 채울 도구를 고르세요: next는 "wiki" 또는 "dart".\n'
    "  query에는 **빠진 부분을 콕 집은** 구체적 한국어 질의를 적으세요. 같은 도구라도 더 구체적인\n"
    "  질의로 다시 부를 수 있습니다(이미 충분히 모은 부분을 반복하지는 마세요).\n"
    '- 충분하면 next는 "FINISH"(종합 단계로 넘어갑니다, query는 빈 문자열).\n'
    "- thought에는 무엇이 충분하고 무엇이 부족한지 한 줄로 적으세요.\n"
    '형식: {"next": "wiki"|"dart"|"FINISH", "query": "<질의>", "thought": "<충분/부족 판단>"}'
)


def _decide(question: str, called: list[str], gathered: list[str], digest: str = "") -> dict:
    """One **evidence-aware** supervisor decision: judge whether the gathered material (``digest``)
    suffices, and either name a spoke + a gap-targeted sub-query, or FINISH (hand off to the
    synthesizer). Plain JSON completion — no tool-calling. Defaults to FINISH on a parse failure."""
    system = load_prompt("supervisor") + "\n\n" + _DECISION_DIRECTIVE
    user = (
        f"질문: {question}\n"
        f"지금까지 호출한 도구: {sorted(set(called)) or '없음'}\n"
        f"수집 요약:\n{digest or '(아직 없음)'}\n\n"
        "위 자료가 질문에 충분한지 판단하고 다음 행동을 JSON으로 출력하세요."
    )
    try:
        raw = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=200, timeout=60.0
        )
        act = parse_action(raw) or {}
    except Exception as e:  # noqa: BLE001 — a decision must never hard-fail; finish with what we have
        # but DON'T fail silently: a timeout/endpoint error here is otherwise indistinguishable from
        # a legit "FINISH", hiding vLLM degradation. Log it so the early finish is observable.
        log.warning("supervisor _decide() failed (%s: %s) — defaulting to FINISH", type(e).__name__, e)
        act = {}
    nxt = (act.get("next") or "FINISH").strip()
    return {"next": nxt, "query": (act.get("query") or question).strip(), "thought": act.get("thought", "")}


# --- nodes ------------------------------------------------------------------------------


async def _supervisor_node(state: SupervisorState):
    """Decide the next hop **on the substance gathered so far**: re-dispatch a spoke to fill a gap,
    or hand off to the synthesizer (``finalize``) when the evidence suffices. Loop-safe: a
    re-dispatch that adds no new material (`stalled`) or the `_MAX_TURNS` cap forces a finish; an
    empty finish is grounded via the wiki first."""
    from langgraph.types import Command

    turns = state.get("turns", 0) + 1
    called = state.get("called", [])
    evidence = state.get("evidence", [])
    findings = state.get("findings", {}) or {}
    gathered = _gathered(state)
    sig = _progress_sig(evidence, findings)
    prev = state.get("last_sig")
    stalled = prev is not None and sig == prev    # the dispatch we just made added nothing new
    capped = turns > _MAX_TURNS

    # Hard termination: no progress, or out of turns, and we already have something → synthesize it.
    if (stalled or capped) and gathered:
        why = "정체(추가 근거 없음) → 종합" if stalled else "최대 라운드 도달 → 종합"
        rec = {"agent": "supervisor", "action": "route", "arg": "synthesizer", "thought": why}
        return Command(goto="finalize", update={"turns": turns, "last_sig": sig, "trace": [rec]})

    # Evidence-aware decision: judge sufficiency, name a gap-targeted spoke or FINISH.
    digest = _evidence_digest(evidence, findings)
    d = await asyncio.to_thread(_decide, state["question"], called, gathered, digest)
    nxt, query, thought = d["next"], d["query"], d["thought"]

    if nxt in ("wiki", "dart") and not capped:     # re-dispatch allowed (gap-fill); cap is the backstop
        rec = {"agent": "supervisor", "action": "call", "arg": f"{nxt}({query[:80]})", "thought": thought}
        return Command(goto=nxt, update={"next_query": query, "turns": turns, "last_sig": sig, "trace": [rec]})

    # finishing (FINISH / capped) — but never finish empty-handed
    if not gathered and "wiki" not in called:
        rec = {"agent": "supervisor", "action": "call", "arg": "wiki(grounding)", "thought": thought}
        return Command(goto="wiki",
                       update={"next_query": state["question"], "turns": turns, "last_sig": sig, "trace": [rec]})
    # hand off to the synthesizer spoke (action="route" is the streaming path's finish signal)
    rec = {"agent": "supervisor", "action": "route", "arg": "synthesizer", "thought": thought}
    return Command(goto="finalize", update={"turns": turns, "last_sig": sig, "trace": [rec]})


def _make_wiki_node(store: Any, max_steps: int | None = None):
    """Wiki research spoke, closing over the per-request ``store`` (concurrency-safe) and the
    caller's ``max_steps`` read budget. Does *research only* (``aresearch``) — returns cell-anchored
    evidence; the synthesizer, not this spoke, writes the answer."""

    async def _wiki_node(state: SupervisorState):
        from langgraph.types import Command

        from ..core import aresearch  # deferred: avoid a core <-> supervisor import cycle

        q = state.get("next_query") or state["question"]
        out = await aresearch(q, store=store, max_steps=max_steps)
        trace = _tag(out.get("trace", []), "wiki")
        n = len(out.get("evidence", []))
        trace.append({"agent": "supervisor", "action": "result", "arg": f"wiki: {n} fact(s)", "thought": ""})
        return Command(
            goto="supervisor",
            update={
                "evidence": out.get("evidence", []),
                "paths": out.get("paths", []),
                "caveats": out.get("caveats", []),
                "called": ["wiki"],
                "trace": trace,
            },
        )

    return _wiki_node


async def _dart_node(state: SupervisorState):
    """DART research spoke — the public-company tool-calling agent. Returns prose findings (no
    cell-anchored evidence); the synthesizer folds them into the final answer. Uses the guarded
    ``arun_safe`` so a DART outage becomes an error note in ``findings`` rather than raising — which
    would unwind the graph and discard wiki evidence already gathered this run."""
    from langgraph.types import Command

    from .dart import arun_safe as dart_arun

    q = state.get("next_query") or state["question"]
    out = await dart_arun(q)
    ans = out.get("answer", "")
    trace = _tag(out.get("trace", []), "dart")
    trace.append({"agent": "supervisor", "action": "result", "arg": f"dart: {ans[:120]}", "thought": ""})
    return Command(goto="supervisor", update={"findings": {"dart": ans}, "called": ["dart"], "trace": trace})


async def _finalize_node(state: SupervisorState) -> dict:
    """The synthesizer spoke (buffered): write the final answer over **all** gathered research,
    following the shared :func:`_synthesis_plan` (so it can't diverge from the streaming path)."""
    from .wiki.synthesize import synthesize

    plan = _synthesis_plan(state)
    if plan["mode"] == "synthesize":
        answer, _ = await asyncio.to_thread(synthesize, plan["synth_state"])
        return {"answer": answer, "source": plan["source"],
                "trace": [{"agent": "synthesizer", "action": "answer", "arg": "", "thought": ""}]}
    if plan["mode"] == "passthrough":
        return {"answer": plan["text"], "source": plan["source"],
                "trace": [{"agent": "synthesizer", "action": "passthrough", "arg": plan["source"], "thought": ""}]}
    return {"answer": "", "source": "none"}


def _build_supervisor(store: Any, max_steps: int | None = None):
    """Compile the supervisor graph; the wiki spoke closes over the per-request ``store`` and
    ``max_steps``. Factored out so tests can drive a real graph with stubbed nodes/LLM offline."""
    g = StateGraph(SupervisorState)
    g.add_node("supervisor", _supervisor_node)
    g.add_node("wiki", _make_wiki_node(store, max_steps))
    g.add_node("dart", _dart_node)
    g.add_node("finalize", _finalize_node)
    g.add_edge(START, "supervisor")  # supervisor/spoke nodes route dynamically via Command(goto)
    g.add_edge("finalize", END)
    return g.compile()


# --- public API (unchanged signatures: core.py / api dispatch here) ----------------------


def _seed(question: str) -> SupervisorState:
    return {"question": question, "evidence": [], "paths": [], "caveats": [],
            "findings": {}, "called": [], "trace": [], "turns": 0}


_LIMIT = {"recursion_limit": 25}


async def _fallback(question: str, store: Any, max_steps: int | None = None) -> dict:
    """Degrade to the cheap classifier + direct dispatch when the supervisor graph fails."""
    from ..core import arun, route

    try:
        src = await asyncio.to_thread(route, question)
    except Exception:  # noqa: BLE001 — routing must never hard-fail
        src = "wiki"
    if src == "dart":
        from .dart import arun_safe as dart_arun  # guarded: a dart outage must not escape the fallback

        return {"source": "dart", **(await dart_arun(question))}
    out = await arun(question, store=store, max_steps=max_steps)
    return {
        "source": "wiki",
        "answer": out["answer"],
        "trace": out["trace"],
        "steps": out["steps"],
        "evidence": out.get("evidence", []),
    }


async def arun_supervised(question: str, store: Any = None, max_steps: int | None = None) -> dict:
    """Answer via the supervisor graph. Returns ``{source, answer, trace, steps, evidence}``.

    Drives the graph through its ``finalize`` (synthesizer) node; on any failure (or an
    empty/ungrounded result) degrades to ``route`` + direct dispatch so the request still gets a
    grounded answer."""
    try:
        final: dict = await _build_supervisor(store, max_steps).ainvoke(_seed(question), config=_LIMIT)
    except Exception:  # noqa: BLE001 — graph/endpoint failure → degrade gracefully
        return await _fallback(question, store, max_steps)

    answer = (final.get("answer") or "").strip()
    if not answer or final.get("source") == "none":  # nothing gathered → ground via the wiki
        return await _fallback(question, store, max_steps)
    trace = _renumber(final.get("trace", []))
    return {
        "source": final.get("source") or _source_label(final.get("evidence", []), final.get("findings", {})),
        "answer": answer,
        "trace": trace,
        "steps": _count_calls(trace),
        "evidence": final.get("evidence", []),
    }


def run_supervised(question: str, store: Any = None, max_steps: int | None = None) -> dict:
    """Sync wrapper around :func:`arun_supervised` (CLI / sync ``core.answer``)."""
    return asyncio.run(arun_supervised(question, store=store, max_steps=max_steps))


def _chunk(text: str, size: int = 24) -> list[str]:
    """Split a finished answer into replay fragments for token-style SSE delivery."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [text]


async def astream_supervised(question: str, store: Any = None, max_steps: int | None = None):
    """Async generator of ``step``/``token``/``answer`` events for the SSE endpoint.

    Drives the supervisor graph for the research/decision **``step``** events (supervisor + wiki +
    dart). When the supervisor hands off to the synthesizer (its ``route`` step), it stops driving
    the graph **before** the buffered ``finalize`` node and instead streams the synthesizer's *real*
    tokens (``synthesize_stream``) outside the graph — so the answer streams token-by-token for every
    auto question, composite included. (DART-only answers are already complete prose, so they're
    replayed as chunks.) Note: a pure-wiki question first pays the supervisor's two decision calls, so
    it is slower-to-first-token than the removed ``route()=="wiki"`` fast-path — the deliberate cost of
    routing all auto traffic through the central supervisor. On a graph failure or an ungrounded
    result, degrades to the direct wiki token stream."""
    from ..core import _aiter_in_thread, astream_run, evidence_sources

    emitted = 0
    final: dict = {}
    finishing = False
    try:
        async for state in _build_supervisor(store, max_steps).astream(
                _seed(question), config=_LIMIT, stream_mode="values"):
            final = state
            trace = state.get("trace", [])
            while emitted < len(trace):
                e = trace[emitted]
                yield {
                    "type": "step",
                    "step": emitted,
                    "agent": e.get("agent", ""),
                    "action": e.get("action", ""),
                    "arg": e.get("arg", ""),
                    "thought": e.get("thought", ""),
                }
                if e.get("agent") == "supervisor" and e.get("action") == "route":
                    finishing = True  # supervisor handed off to the synthesizer → synth outside
                emitted += 1
            if finishing:  # stop before the buffered finalize node runs; we stream synth instead
                break
    except Exception:  # noqa: BLE001 — degrade to a direct wiki stream
        async for ev in astream_run(question, max_steps=max_steps, store=store, source="wiki"):
            yield ev
        return

    plan = _synthesis_plan(final)                  # SAME decision the buffered finalize node uses
    if plan["mode"] == "none":  # ungrounded → wiki stream instead of guessing
        async for ev in astream_run(question, max_steps=max_steps, store=store, source="wiki"):
            yield ev
        return

    parts: list[str] = []
    if plan["mode"] == "synthesize":  # central synthesis over all gathered research — real token stream
        from .wiki.synthesize import synthesize_stream

        async for delta in _aiter_in_thread(lambda: synthesize_stream(plan["synth_state"])):
            parts.append(delta)
            yield {"type": "token", "text": delta}
        answer = "".join(parts).strip()
    else:  # passthrough (dart-only) → replay its verbatim cited answer
        answer = plan["text"]
        for piece in _chunk(answer):
            yield {"type": "token", "text": piece}

    yield {"type": "answer", "answer": answer or "(답변 없음)",
           "steps": _count_calls(final.get("trace", [])),
           "sources": evidence_sources(final.get("evidence", []), store.index if store is not None else None)}


if __name__ == "__main__":
    import sys

    from src.stella_kb import config

    q = " ".join(sys.argv[1:]) or "센트로이드 기업가치는 얼마인가요?"
    print(f"tool LLM: {config.tool_llm_url()} ({config.tool_llm_model()})\n")
    out = run_supervised(q)
    for e in out["trace"]:
        print(f"  [{e['agent']}] {e['action']}: {e['arg']}")
    print(f"\nsource: {out['source']}  steps: {out['steps']}\n")
    print(out["answer"])
