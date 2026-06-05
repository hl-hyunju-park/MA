"""Public API of the wiki query agent: ``run`` / ``ask`` / ``stream_run``.

Each seeds the multi-agent pipeline (``apps.agent.graph``: planner → router → retriever →
verifier → synthesizer) with the wiki's ``INDEX.md`` table of contents and the question,
then drives it to a cited Korean answer. The router is handed the ToC and must navigate to
the right page on its own, using only the deterministic ``apps.agent.io`` reads.

  - ``run``         → ``{answer, trace, steps}`` (trace = the per-agent routing record)
  - ``ask``         → just the answer string
  - ``stream_run``  → generator of routing events, for live (SSE) display
"""

from __future__ import annotations

from typing import Any

from .graph import AgentState, build_app
from .io import INDEX_MD, load_index


def _seed(question: str, max_steps: int, verbose: bool = False) -> AgentState:
    """Initial graph state: INDEX ToC + the question. Each node builds its own prompt."""
    return {
        "question": question,
        "index_md": INDEX_MD.read_text(encoding="utf-8"),
        "plan": [], "cursor": 0, "pages": [], "tried_pages": [], "evidence": [],
        "trace": [], "steps": 0, "max_steps": max_steps, "retries": 0,
        "verbose": verbose,
    }


def _limit(max_steps: int) -> dict:
    # per sub-question attempt = router+retriever+verifier (3 supersteps); give headroom
    return {"recursion_limit": max_steps * 4 + 10}


def run(question: str, max_steps: int = 8, verbose: bool = False,
        index: dict | None = None) -> dict[str, Any]:
    """Navigate the wiki to answer ``question``; return ``{answer, trace, steps}``.

    ``trace`` is the per-turn routing record (which page it opened, why) — the whole point
    of testing the index as a lookup table. Pass ``verbose=True`` to also print it.
    """
    app = build_app(index if index is not None else load_index())
    final: dict[str, Any] = app.invoke(_seed(question, max_steps, verbose),
                                       config=_limit(max_steps))
    return {"answer": (final.get("answer") or "(no answer)").strip(),
            "trace": final.get("trace", []),
            "steps": final.get("steps", 0)}


def ask(question: str, max_steps: int = 8, verbose: bool = False,
        index: dict | None = None) -> str:
    """Convenience wrapper around :func:`run` that returns just the answer string."""
    return run(question, max_steps=max_steps, verbose=verbose, index=index)["answer"]


def stream_run(question: str, max_steps: int = 8, index: dict | None = None):
    """Generator yielding routing events as the agent navigates, for live (SSE) display.

    Uses LangGraph's native ``app.stream(stream_mode="values")``: after every node the
    full state is emitted, so new ``trace`` entries surface as the agent makes each
    decision. Event dicts carry a ``type``:

      {"type": "step",   "step": int, "action": str, "arg": str, "thought": str}
      {"type": "answer", "answer": str, "steps": int}
    """
    app = build_app(index if index is not None else load_index())
    emitted = 0
    final: dict[str, Any] = {}
    for state in app.stream(_seed(question, max_steps), config=_limit(max_steps),
                            stream_mode="values"):
        final = state
        trace = state.get("trace", [])
        while emitted < len(trace):                       # surface each new decision
            yield {"type": "step", **trace[emitted]}
            emitted += 1
    if final.get("answer"):
        yield {"type": "answer", "answer": final["answer"], "steps": final.get("steps", 0)}
