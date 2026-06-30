"""Deterministic offline tests for the hierarchical drill-down navigator (LLM pick stubbed).

The per-level folder choice (``_pick``) is the only LLM call; it's monkeypatched so the walk,
early-stop, and within-candidate lookup ranking are tested without the network.
"""

from __future__ import annotations

from apps.agent.cores.wiki import navigate as nv


def _index(alias_index=None):
    folders = {
        "1": {"num": "1", "name": "회사", "label": "1. 회사", "desc": "",
              "children": ["1.1"], "pages": [], "n_pages": 3},
        "1.1": {"num": "1.1", "name": "평가", "label": "1.1. 평가", "desc": "",
                "children": [], "pages": ["p_a", "p_b", "p_c"], "n_pages": 3},
        "2": {"num": "2", "name": "재무", "label": "2. 재무", "desc": "",
              "children": ["2.1"], "pages": [], "n_pages": 1},
        "2.1": {"num": "2.1", "name": "제표", "label": "2.1. 제표", "desc": "",
                "children": [], "pages": ["p_d"], "n_pages": 1},
    }
    return {"nav": {"roots": ["1", "2"], "folders": folders},
            "pages": {k: {} for k in ("p_a", "p_b", "p_c", "p_d")},
            "alias_index": alias_index or {}}


def _pick_label(substr):
    """A deterministic stand-in for the LLM pick (signature matches the new file-reading ``_pick``:
    ``(ask, doc, candidates, folders, where)``): choose a candidate whose label contains ``substr``,
    else descend into the first candidate."""
    return lambda ask, doc, candidates, folders, where: \
        ([c for c in candidates if substr in folders[c]["label"]] or candidates)[:1]


def test_navigate_no_nav_returns_empty():
    assert nv.navigate("q", {"pages": {}}) == []


def test_navigate_drills_to_chosen_leaf(monkeypatch):
    monkeypatch.setattr(nv, "_pick", _pick_label("재무"))
    # root pick 2.재무 → descend to 2.1 (n_pages=1 ≤ cap) → its page
    assert nv.navigate("재무 질문", _index(), ["x"]) == ["p_d"]


def test_navigate_early_stop_takes_whole_subtree(monkeypatch):
    monkeypatch.setattr(nv, "_pick", _pick_label("회사"))
    # 1.회사 subtree (3 pages) ≤ page_cap → grabbed wholesale at the root pick, no deeper hop
    assert set(nv.navigate("회사 질문", _index(), ["x"])) == {"p_a", "p_b", "p_c"}


def test_navigate_lookup_ranks_within_candidates(monkeypatch):
    monkeypatch.setattr(nv, "_pick", _pick_label("회사"))
    idx = _index(alias_index={"target": [{"page": "p_c", "cell": "A1", "term": "target"}]})
    # 3 candidates but page_cap=1 → alias lookup over hints surfaces p_c first → it survives the cap
    assert nv.navigate("회사 질문", idx, ["target"], page_cap=1) == ["p_c"]


def test_navigate_stops_when_pick_empty(monkeypatch):
    monkeypatch.setattr(nv, "_pick", lambda ask, doc, candidates, folders, where: [])
    assert nv.navigate("q", _index(), ["x"]) == []


def test_navigate_reads_router_and_index_files(monkeypatch, tmp_path):
    """The agent OPENS router.yaml + the chosen folder's index.md — _pick receives that file text."""
    seen = []
    monkeypatch.setattr(nv, "_pick",
                        lambda ask, doc, candidates, folders, where: (seen.append((where, doc)), candidates[:1])[1])
    (tmp_path / "router.yaml").write_text("ROUTER-FILE-CONTENT", encoding="utf-8")
    idx = _index()
    idx["nav"]["folders"]["1"]["md"] = "nav/1/index.md"
    (tmp_path / "nav" / "1").mkdir(parents=True)
    (tmp_path / "nav" / "1" / "index.md").write_text("INDEX-FILE-CONTENT", encoding="utf-8")
    nv.navigate("q", idx, ["x"], page_cap=1, wiki_dir=str(tmp_path))
    wheres = [w for w, _ in seen]
    assert wheres[0] == "router.yaml" and seen[0][1] == "ROUTER-FILE-CONTENT"   # read the file
    assert any("index.md" in w for w, _ in seen)
    assert any(d == "INDEX-FILE-CONTENT" for _, d in seen)                       # read the index.md


def test_subtree_pages_recurses():
    folders = _index()["nav"]["folders"]
    assert nv._subtree_pages("1", folders) == ["p_a", "p_b", "p_c"]
    assert nv._subtree_pages("2", folders) == ["p_d"]
