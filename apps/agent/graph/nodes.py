"""The five agent nodes of the QA pipeline: planner → router → retriever → verifier →
synthesizer. Each node owns one LLM persona (a prompt in ``apps.agent.prompts``), builds
its prompt fresh from :class:`AgentState`, and emits ONE JSON object. The deterministic
wiki reads (``lookup``/``open_page`` in ``apps.agent.io``) do all retrieval — the LLMs
only route and write prose. The shared vLLM has no native tool-calling, hence the
JSON-per-turn (ReAct-style) contract.
"""

from __future__ import annotations

import json

from src.stella_kb.llm import chat

from ..io import lookup, open_page
from ..prompts import load as load_prompt
from .state import AgentState

PLANNER = load_prompt("planner")
ROUTER = load_prompt("router")
RETRIEVER = load_prompt("retriever")
VERIFIER = load_prompt("verifier")
SYNTHESIZER = load_prompt("synthesizer")

_MAX_RETRY = 2  # verifier→router retries allowed per sub-question


def parse_action(raw: str) -> dict | None:
    """Extract the single JSON object from a model turn (tolerates code fences/prose)."""
    s = raw.strip()
    if "```" in s:
        parts = s.split("```")
        s = max(parts, key=len).lstrip("json").strip() if len(parts) >= 3 else s.strip("`")
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(s[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def _ask(system: str, user: str, max_tokens: int) -> tuple[dict | None, str]:
    """One-shot LLM call: system + user → (parsed JSON action, raw text)."""
    raw = chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        timeout=120.0,
    )
    return parse_action(raw), raw


def _entry(state: AgentState, agent: str, action: str, arg: str, thought: str) -> list:
    """One trace record as a single-item delta; the ``trace`` reducer appends it.

    ``step`` is the running entry count read from the current trace (the pipeline is
    linear, so this index is deterministic)."""
    step = len(state.get("trace", []))
    return [{"step": step, "agent": agent, "action": action, "arg": arg, "thought": thought}]


# --------------------------------------------------------------------------- planner
def planner_node(state: AgentState) -> AgentState:
    """Break the question into a minimal ordered list of sub-questions (usually one)."""
    user = (f"INDEX:\n{state['index_md']}\n\nQuestion: {state['question']}\n\n"
            "Return the plan JSON.")
    act, _ = _ask(PLANNER, user, 600)
    plan = [p for p in ((act or {}).get("plan") or []) if isinstance(p, dict) and p.get("ask")]
    if not plan:  # parse miss / empty → fall back to a single pass-through sub-question
        plan = [{"ask": state["question"], "hint_terms": []}]
    if state.get("verbose"):
        print(f"[planner] {len(plan)} sub-question(s)")
    return {
        "plan": plan, "cursor": 0, "retries": 0, "tried_pages": [], "pages": [],
        "trace": _entry(state, "planner", "plan",
                        f"{len(plan)} sub-Q", (act or {}).get("thought", "")),
    }


# ---------------------------------------------------------------------------- router
def router_node(state: AgentState, index: dict) -> AgentState:
    """Pick the wiki page(s) for the current sub-question (whitelist-guarded to the INDEX)."""
    sub = state["plan"][state["cursor"]]
    hints = sub.get("hint_terms") or []
    lookups = "\n\n".join(lookup(index, t) for t in hints) if hints else "(no hint terms)"
    tried = state.get("tried_pages", [])
    avoid = (f"\nAlready tried for this sub-question and found insufficient — pick a "
             f"DIFFERENT page unless re-reading is clearly justified: {tried}") if tried else ""
    user = (f"INDEX:\n{state['index_md']}\n\nLookup results:\n{lookups}\n\n"
            f"Sub-question: {sub['ask']}{avoid}\n\nReturn the pages JSON.")
    act, _ = _ask(ROUTER, user, 400)
    valid = set(index.get("pages", {}).keys())
    picks = [p for p in ((act or {}).get("pages") or []) if p in valid]  # drop hallucinated pages
    if state.get("verbose"):
        print(f"[router] sub#{state['cursor']} -> {picks}")
    return {
        "pages": picks,
        "trace": _entry(state, "router", "route",
                        ", ".join(picks) or "(none)", (act or {}).get("thought", "")),
    }


# ------------------------------------------------------------------------- retriever
def retriever_node(state: AgentState) -> AgentState:
    """Open the chosen page(s) and extract the line items relevant to the sub-question."""
    ask = state["plan"][state["cursor"]]["ask"]
    pages = state.get("pages", [])
    texts = {p: open_page(p) for p in pages}
    blob = "\n\n".join(texts.values()) if texts else "(no pages selected)"
    user = f"Sub-question: {ask}\n\nWIKI PAGES:\n{blob}\n\nReturn the evidence JSON."
    act, _ = _ask(RETRIEVER, user, 800)

    ev: list[dict] = []
    for e in (act or {}).get("evidence") or []:
        if not isinstance(e, dict):
            continue
        cell = str(e.get("cell", ""))
        celltok = cell.split("!")[-1]  # soft guard: the cell must appear on an opened page
        if celltok and any(celltok in t for t in texts.values()):
            ev.append({"page": e.get("page", ""), "cell": cell,
                       "term": e.get("term", ""), "value": str(e.get("value", "")), "ask": ask})
    if state.get("verbose"):
        print(f"[retriever] +{len(ev)} evidence from {pages}")
    return {
        "evidence": ev,                                           # reducer appends to the run
        "tried_pages": list(state.get("tried_pages", [])) + pages,  # overwrite channel: extend by hand
        "steps": state.get("steps", 0) + 1,
        "trace": _entry(state, "retriever", "read",
                        f"{len(ev)} fact(s) from {pages}", (act or {}).get("thought", "")),
    }


# -------------------------------------------------------------------------- verifier
def verifier_node(state: AgentState) -> AgentState:
    """Judge whether the sub-question is answered; route to retry / next / synthesize."""
    cur = state["cursor"]
    ask = state["plan"][cur]["ask"]
    ev = [e for e in state.get("evidence", []) if e.get("ask") == ask]
    ev_txt = "\n".join(f"- {e['term']} = {e['value']}  ({e['cell']}, {e['page']})" for e in ev) or "(no evidence)"
    user = f"Sub-question: {ask}\n\nEvidence:\n{ev_txt}\n\nReturn the verdict JSON."
    act, _ = _ask(VERIFIER, user, 300)

    verdict = ((act or {}).get("verdict") or ("ok" if ev else "gap")).lower()
    retries = state.get("retries", 0)
    over_budget = state.get("steps", 0) >= state["max_steps"]
    last = cur >= len(state["plan"]) - 1

    if verdict == "gap" and not over_budget and retries < _MAX_RETRY:
        route, out = "retry", {"retries": retries + 1}            # same sub-Q, avoid tried pages
    elif last:
        route, out = "synthesize", {}
    else:
        route, out = "next", {"cursor": cur + 1, "retries": 0, "tried_pages": [], "pages": []}
    if state.get("verbose"):
        print(f"[verifier] {verdict} -> {route}")
    return {
        "route": route,
        "trace": _entry(state, "verifier", "verify",
                        f"{verdict} -> {route}", (act or {}).get("reason", "")),
        **out,
    }


# ----------------------------------------------------------------------- synthesizer
def synthesizer_node(state: AgentState) -> AgentState:
    """Write the final cited Korean answer from the accumulated evidence only."""
    ev = state.get("evidence", [])
    ev_txt = "\n".join(
        f"- [{e['ask']}] {e['term']} = {e['value']}  ({e['cell']}, page {e['page']})" for e in ev
    ) or "(no evidence gathered)"
    user = (f"Question: {state['question']}\n\nEvidence collected from the wiki:\n{ev_txt}\n\n"
            "Write the final answer JSON.")
    act, raw = _ask(SYNTHESIZER, user, 700)
    text = ((act or {}).get("text") or raw or "").strip() or "(빈 답변)"
    return {
        "answer": text,
        "trace": _entry(state, "synthesizer", "answer", "", (act or {}).get("thought", "")),
    }
