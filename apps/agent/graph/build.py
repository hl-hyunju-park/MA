"""Wire the five agent nodes into a compiled LangGraph ``StateGraph``.

    START → planner → router → retriever → verifier ─┬─ "retry"      → router
                                                     ├─ "next"       → router
                                                     └─ "synthesize" → synthesizer → END

``index`` is bound to the ``router`` node here (it needs the alias index for ``lookup`` and
the page-name whitelist), keeping the node functions in ``nodes.py`` pure.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    planner_node,
    retriever_node,
    router_node,
    synthesizer_node,
    verifier_node,
)
from .state import AgentState


def build_app(index: dict):
    """Compile the multi-agent routing graph; ``index`` is closed over by the router."""
    g = StateGraph(AgentState)
    g.add_node("planner", planner_node)
    g.add_node("router", lambda s: router_node(s, index))
    g.add_node("retriever", retriever_node)
    g.add_node("verifier", verifier_node)
    g.add_node("synthesizer", synthesizer_node)

    g.add_edge(START, "planner")
    g.add_edge("planner", "router")
    g.add_edge("router", "retriever")
    g.add_edge("retriever", "verifier")
    g.add_conditional_edges("verifier", lambda s: s["route"],
                            {"retry": "router", "next": "router", "synthesize": "synthesizer"})
    g.add_edge("synthesizer", END)
    return g.compile()
