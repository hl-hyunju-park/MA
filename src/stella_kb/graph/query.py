"""Query layer: resolve a question to a Metric node, traverse the graph for evidence,
synthesize an answer. Follows the DCI loop (resolve -> inspect -> synthesize) with the
project's split: the **LLM only maps words->nodes and writes the final prose**; all
evidence comes from deterministic graph traversal, and every number carries its source cell.

    from src.stella_kb.graph.query import ask
    print(ask("What is the equity value and what drives it?"))

Run ``python -m src.stella_kb.graph.semantic`` once first to write ``data/stella_graph.json``.
"""

from __future__ import annotations

import json

import networkx as nx

from .. import DATA_DIR
from .. import llm

GRAPH_PATH = str(DATA_DIR / "stella_graph.json")


# --- load ------------------------------------------------------------------------------

def load_graph(path: str = GRAPH_PATH) -> nx.DiGraph:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return nx.node_link_graph(data, edges="edges")


# --- deterministic retrieval -----------------------------------------------------------

def _label(g: nx.DiGraph, n: str) -> str:
    return g.nodes[n].get("label", n.split(":", 1)[-1])


def series(g: nx.DiGraph, mid: str) -> list[tuple]:
    """``[(year, value, cell), ...]`` from this metric's HAS_VALUE edges, year-sorted."""
    out = []
    for _, p, d in g.out_edges(mid, data=True):
        if d.get("type") == "HAS_VALUE":
            out.append((g.nodes[p].get("year"), d.get("value"), d.get("cell")))
    return sorted(out, key=lambda t: (1, 0) if isinstance(t[0], str) else (0, t[0]))


def source_cells(g: nx.DiGraph, mid: str) -> list[str]:
    return [v.split(":", 1)[-1] if v.startswith("Sheet:") else v
            for _, v, d in g.out_edges(mid, data=True)
            if d.get("type") == "DEFINED_IN"]


def drivers(g: nx.DiGraph, mid: str, max_depth: int = 6) -> list[tuple]:
    """Reverse DRIVES/ASSUMPTION_OF walk: what feeds ``mid``. ``[(depth, label, rel), ...]``."""
    out, seen = [], set()

    def up(node, depth):
        if depth > max_depth:
            return
        for u, _, d in g.in_edges(node, data=True):
            rel = d.get("type")
            if rel in ("DRIVES", "ASSUMPTION_OF") and (u, node) not in seen:
                seen.add((u, node))
                out.append((depth, _label(g, u), rel))
                up(u, depth + 1)

    up(mid, 0)
    return out


def evidence(g: nx.DiGraph, mid: str) -> str:
    """A compact, grounded evidence block for one metric — the only thing the LLM sees."""
    n = g.nodes[mid]
    lines = [f"Metric: {n.get('label')} (id={mid.split(':',1)[-1]}, category={n.get('category')}"
             + (f", case={n.get('case')}" if n.get("case") else "") + ")"]
    if n.get("label_ko"):
        lines.append(f"Korean label: {n['label_ko']}")
    if n.get("value") is not None:
        lines.append(f"Value: {n['value']}  [cells: {', '.join(source_cells(g, mid)) or '—'}]")
    s = series(g, mid)
    if s:
        lines.append("By period:")
        for yr, val, cell in s:
            vs = f"{val:,.1f}" if isinstance(val, (int, float)) else str(val)
            lines.append(f"  {yr}: {vs}  [{cell}]")
    dr = drivers(g, mid)
    if dr:
        lines.append("Drives/assumptions feeding it (depth · label · relation):")
        for depth, lbl, rel in dr:
            lines.append(f"  {'  ' * depth}- {lbl} ({rel})")
    return "\n".join(lines)


# --- resolve + answer ------------------------------------------------------------------

def resolve(question: str) -> str | None:
    """Question -> Metric node id (``Metric:...``) via the whitelist-guarded LLM mapper."""
    r = llm.resolve_metric(question)
    return f"Metric:{r['id']}" if r.get("id") else None


def ask(question: str, synthesize: bool = True, g: nx.DiGraph | None = None) -> str:
    """Resolve -> gather graph evidence -> (optionally) LLM-synthesize a cited answer."""
    if g is None:
        g = load_graph()
    mid = resolve(question)
    if mid is None or mid not in g:
        return "Could not resolve the question to a known metric in the graph."
    ev = evidence(g, mid)
    if not synthesize:
        return ev
    sys = (
        "You answer M&A valuation questions about Centroid using ONLY the evidence block. "
        "Do not invent numbers. Cite the source cell (e.g. DCF!K59) for every figure you "
        "state. Units are KRW millions unless the value is a rate/date. Be concise."
    )
    user = f"Question: {question}\n\nEvidence:\n{ev}\n\nAnswer:"
    return llm.chat([{"role": "system", "content": sys}, {"role": "user", "content": user}],
                    max_tokens=400)


if __name__ == "__main__":
    g = load_graph()
    print(f"loaded graph: {g.number_of_nodes()} nodes, {g.number_of_edges()} edges\n")
    for q in [
        "What is the equity value and what drives it?",
        "관리수수료 추이가 어떻게 되나요?",          # "how does the management fee trend?"
        "What discount rate (WACC) is used?",
    ]:
        print("Q:", q)
        print(ask(q, g=g))
        print("-" * 70)
