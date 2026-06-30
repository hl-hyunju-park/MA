"""Diff two eval runs to explain *why* items changed score — the regression debugger.

The v0.2 eval is noisy (the shared vLLM is non-deterministic), so an A/B that nets a wash
often hides a real story: a fix recovered its targets but regressed others (e.g. the retriever
A/B took L09/L06 1.0→0.0 while lifting L07/CE-01). ``answers.json`` records *what the agent saw*
per item — ``pages_opened``, the cell-anchored ``evidence`` the synthesizer received, and the
``router_paths`` (routes.yaml / resolver / router) taken — and ``scores.json`` records the judged
score. This tool joins the two across two run dirs and, for every item whose score moved, prints
the delta in pages / evidence / path. That turns "L09 regressed" into "L09 lost evidence row
``FDD9!… = 177`` and opened a different page", which is actionable.

Each run dir is a ``knowledge/eval/<run>`` directory holding ``answers.json`` + ``scores.json``
(as written by ``eval.qa_eval``). Older runs that predate the ``evidence``/``router_paths``
fields still diff on score + ``pages_opened`` (missing fields degrade to empty, never crash).

Usage (from repo root, venv active):
    python -m eval.diff_runs knowledge/eval/v0.2_now_1 knowledge/eval/v0.2_now_2
    python -m eval.diff_runs <baseline_dir> <treatment_dir> --all   # also list unchanged
"""

from __future__ import annotations

import json
from pathlib import Path


def _load(run_dir: Path) -> dict[str, dict]:
    """Join ``answers.json`` + ``scores.json`` for one run into ``{id: merged_record}``.

    Missing files / fields degrade to empty so a run that predates the richer ``answers.json``
    (no ``evidence``/``router_paths``) still diffs on score + pages."""
    answers = {a["id"]: a for a in _read_json(run_dir / "answers.json")}
    scores = {s["id"]: s for s in _read_json(run_dir / "scores.json")}
    out: dict[str, dict] = {}
    for rid in set(answers) | set(scores):
        a, s = answers.get(rid, {}), scores.get(rid, {})
        out[rid] = {
            "id": rid,
            "doc": a.get("doc") or s.get("doc"),
            "capability": a.get("capability") or s.get("capability"),
            "visual_type": a.get("visual_type") or s.get("visual_type"),
            "score": s.get("score"),
            "verdict": s.get("verdict", "?"),
            "pages_opened": a.get("pages_opened") or [],
            "evidence": a.get("evidence") or [],
            "router_paths": a.get("router_paths") or [],
        }
    return out


def _read_json(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _ev_key(e: dict) -> str:
    """A fact's identity for set-diffing: page+cell+period+term=value (the grain the agent dedups on)."""
    return f"{e.get('page','')}!{e.get('cell','')} [{e.get('period','')}] {e.get('term','')}={e.get('value','')}"


def _set_delta(before: list, after: list, keyfn=lambda x: x) -> tuple[list, list]:
    """``(removed, added)`` between two lists, compared by ``keyfn`` (order-independent)."""
    b = {keyfn(x): x for x in before}
    a = {keyfn(x): x for x in after}
    removed = [b[k] for k in b if k not in a]
    added = [a[k] for k in a if k not in b]
    return removed, added


def diff(dir_a: Path, dir_b: Path, noise_floor: float = 0.1) -> dict:
    """Compute the per-item diff between two run dirs. Returns a structured result (testable).

    ``noise_floor`` separates real movement from the shared vLLM's run-to-run jitter: an item moves
    to ``improved``/``regressed`` only when ``|delta| > noise_floor``; smaller non-zero deltas land
    in ``within_noise`` so they aren't read as signal (the eval is noisy — see CLAUDE.md)."""
    A, B = _load(dir_a), _load(dir_b)
    shared = sorted(set(A) & set(B))
    items = []
    for rid in shared:
        a, b = A[rid], B[rid]
        sa, sb = a.get("score"), b.get("score")
        delta = (sb - sa) if (isinstance(sa, (int, float)) and isinstance(sb, (int, float))) else None
        pg_rm, pg_add = _set_delta(a["pages_opened"], b["pages_opened"])
        ev_rm, ev_add = _set_delta(a["evidence"], b["evidence"], _ev_key)
        pa_rm, pa_add = _set_delta(a["router_paths"], b["router_paths"])
        items.append({
            "id": rid, "doc": a.get("doc"), "capability": a.get("capability"),
            "score_a": sa, "score_b": sb, "delta": delta,
            "verdict_a": a.get("verdict"), "verdict_b": b.get("verdict"),
            "pages_removed": pg_rm, "pages_added": pg_add,
            "evidence_removed": [_ev_key(e) for e in ev_rm],
            "evidence_added": [_ev_key(e) for e in ev_add],
            "paths_removed": pa_rm, "paths_added": pa_add,
        })
    changed = [it for it in items if it["delta"] not in (None, 0, 0.0)]
    return {
        "shared": len(shared),
        "only_a": sorted(set(A) - set(B)),
        "only_b": sorted(set(B) - set(A)),
        "noise_floor": noise_floor,
        "mean_a": _mean([A[r]["score"] for r in shared if isinstance(A[r]["score"], (int, float))]),
        "mean_b": _mean([B[r]["score"] for r in shared if isinstance(B[r]["score"], (int, float))]),
        "improved": [it for it in changed if it["delta"] > noise_floor],
        "regressed": [it for it in changed if it["delta"] < -noise_floor],
        "within_noise": [it for it in changed if 0 < abs(it["delta"]) <= noise_floor],
        "items": items,
    }


def _mean(xs: list) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _fmt_item(it: dict) -> list[str]:
    arrow = "↑" if it["delta"] > 0 else "↓"
    lines = [
        f"{arrow} {it['id']}  ({it['doc']}/{it['capability']})  "
        f"{it['score_a']}→{it['score_b']}  [{it['verdict_a']}→{it['verdict_b']}]"
    ]
    for label, removed, added in (
        ("pages", it["pages_removed"], it["pages_added"]),
        ("evidence", it["evidence_removed"], it["evidence_added"]),
        ("path", it["paths_removed"], it["paths_added"]),
    ):
        if removed:
            lines += [f"    - {label} removed: {r}" for r in removed]
        if added:
            lines += [f"    + {label} added:   {x}" for x in added]
    return lines


def render(result: dict, dir_a: Path, dir_b: Path, show_all: bool = False) -> str:
    lines = [
        f"# Run diff: {dir_a.name} (A) → {dir_b.name} (B)",
        "",
        f"shared items: {result['shared']}   mean {result['mean_a']:.3f} → {result['mean_b']:.3f} "
        f"(Δ {result['mean_b'] - result['mean_a']:+.3f})",
        f"improved: {len(result['improved'])}   regressed: {len(result['regressed'])}   "
        f"within-noise (|Δ|≤{result['noise_floor']:.2f}): {len(result.get('within_noise', []))}",
        "",
    ]
    if result["only_a"] or result["only_b"]:
        lines.append(f"(only in A: {result['only_a']}  ·  only in B: {result['only_b']})\n")
    if result["regressed"]:
        lines += ["## Regressed", ""]
        for it in sorted(result["regressed"], key=lambda x: x["delta"]):
            lines += _fmt_item(it)
        lines.append("")
    if result["improved"]:
        lines += ["## Improved", ""]
        for it in sorted(result["improved"], key=lambda x: -x["delta"]):
            lines += _fmt_item(it)
        lines.append("")
    if result.get("within_noise"):
        lines += [f"## Within noise (|Δ| ≤ {result['noise_floor']:.2f} — likely not signal)", ""]
        for it in sorted(result["within_noise"], key=lambda x: -abs(x["delta"])):
            lines += _fmt_item(it)
        lines.append("")
    if show_all:
        unchanged = [it for it in result["items"] if it["delta"] in (0, 0.0)]
        lines += ["## Unchanged", ""] + [f"= {it['id']}  {it['score_a']}" for it in unchanged]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    show_all = "--all" in argv
    noise_floor = 0.1
    if "--noise-floor" in argv:                       # --noise-floor 0.05
        i = argv.index("--noise-floor")
        noise_floor = float(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    args = [a for a in argv if not a.startswith("-")]
    if len(args) == 2:
        a_dir, b_dir = Path(args[0]), Path(args[1])
        result = diff(a_dir, b_dir, noise_floor=noise_floor)
        print(render(result, a_dir, b_dir, show_all))
    else:
        # smoke-print: self-contained synthetic diff so the module always runs from repo root.
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as td:
            a, b = Path(td) / "A", Path(td) / "B"
            a.mkdir(); b.mkdir()
            (a / "scores.json").write_text(json.dumps([
                {"id": "Q1", "score": 1.0, "verdict": "correct", "doc": "X", "capability": "C3"},
                {"id": "Q2", "score": 0.0, "verdict": "incorrect", "doc": "X", "capability": "C3"}]))
            (b / "scores.json").write_text(json.dumps([
                {"id": "Q1", "score": 0.0, "verdict": "incorrect", "doc": "X", "capability": "C3"},
                {"id": "Q2", "score": 1.0, "verdict": "correct", "doc": "X", "capability": "C3"}]))
            (a / "answers.json").write_text(json.dumps([
                {"id": "Q1", "pages_opened": ["P1"], "evidence": [{"page": "P1", "cell": "A1", "term": "x", "value": "10"}]},
                {"id": "Q2", "pages_opened": ["P2"], "evidence": []}]))
            (b / "answers.json").write_text(json.dumps([
                {"id": "Q1", "pages_opened": ["P9"], "evidence": []},
                {"id": "Q2", "pages_opened": ["P2"], "evidence": [{"page": "P2", "cell": "B2", "term": "y", "value": "20"}]}]))
            print(render(diff(a, b), a, b, show_all=True))
        print("\n(usage: python -m eval.diff_runs <run_dir_A> <run_dir_B> [--all])")
