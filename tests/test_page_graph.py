"""Page-grain DAG (``semantic.build_page_graph``) — condensation logic, offline.

The headline guarantee is that a mutually-recursive sheet cluster (the Fin.Model engine:
tax↔income↔interest↔debt) condenses into ONE ``Page`` node so the page graph is a true
DAG, unlike the raw sheet→sheet graph. The core test is fully synthetic (no workbook); a
second test sanity-checks the exported artifact when it has been built.
"""

from __future__ import annotations

import json

import networkx as nx
import pytest

from src.stella_kb import DATA_DIR
from src.stella_kb.graph import semantic
from src.stella_kb.graph.extract import DependencyGraph
from src.stella_kb.graph.semantic import SheetClass


def test_engine_cycle_condenses_to_one_page(monkeypatch):
    # Inp -> A, A <-> B (the cycle), B -> Out.  A/B are the engine; condensing them
    # turns the cyclic sheet graph into a clean Inp -> engine -> Out DAG.
    classes = {
        "Inp": SheetClass("Inp", section="Biz Plan", kind="fund"),
        "A": SheetClass("A", section="Fin.Model", kind="engine"),
        "B": SheetClass("B", section="Fin.Model", kind="engine"),
        "Out": SheetClass("Out", section="PPT", kind="exhibit"),
    }
    monkeypatch.setattr(semantic, "classify_sheets", lambda _p: classes)
    dg = DependencyGraph(cells={}, edges=[
        ("Inp!a", "A!a"),   # Inp feeds A
        ("A!x", "B!x"),     # A feeds B
        ("B!y", "A!y"),     # B feeds A  -> A,B strongly connected
        ("B!z", "Out!z"),   # B feeds Out
    ])

    g = semantic.build_page_graph("ignored.xlsx", dg)

    assert nx.is_directed_acyclic_graph(g)
    assert all(d["type"] == "Page" for _, d in g.nodes(data=True))

    engine = [(n, d) for n, d in g.nodes(data=True) if d["kind"] == "engine"]
    assert len(engine) == 1
    eid, ed = engine[0]
    assert eid == "Page:Fin.Model engine"
    assert ed["members"] == ["A", "B"] and ed["n_sheets"] == 2

    # the cycle is gone; flow is Inp -> engine -> Out
    assert g.has_edge("Page:Inp", eid)
    assert g.has_edge(eid, "Page:Out")
    assert g["Page:Inp"][eid]["type"] == "DEPENDS_ON"


def test_two_independent_cycles_get_distinct_page_ids(monkeypatch):
    # two same-section engine clusters must not collide on the dominant-section name
    classes = {s: SheetClass(s, section="Fin.Model", kind="engine") for s in ("A", "B", "C", "D")}
    monkeypatch.setattr(semantic, "classify_sheets", lambda _p: classes)
    dg = DependencyGraph(cells={}, edges=[
        ("A!1", "B!1"), ("B!1", "A!1"),   # cluster {A,B}
        ("C!1", "D!1"), ("D!1", "C!1"),   # cluster {C,D}
    ])

    g = semantic.build_page_graph("ignored.xlsx", dg)
    engine_ids = {n for n, d in g.nodes(data=True) if d["kind"] == "engine"}
    assert len(engine_ids) == 2  # de-duped, no overwrite
    assert "Page:Fin.Model engine" in engine_ids


def test_exported_page_dag_is_acyclic_if_built():
    """The committed/regenerable artifact, when present, is an acyclic Page graph."""
    path = DATA_DIR / "graph" / "stella_pages.json"
    if not path.exists():
        pytest.skip("stella_pages.json not built (run src.stella_kb.graph.semantic)")
    g = nx.node_link_graph(json.loads(path.read_text(encoding="utf-8")), edges="edges")
    assert nx.is_directed_acyclic_graph(g)
    assert all(d.get("type") == "Page" for _, d in g.nodes(data=True))
