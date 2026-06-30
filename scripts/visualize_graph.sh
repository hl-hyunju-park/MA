#!/usr/bin/env bash
#
# Visualize the query agent's FULL architecture as a PNG — open docs/agent_graph.png in your IDE.
#
# The agent is a supervisor-centric HUB-AND-SPOKE (apps/agent/core.py → cores/supervisor.py):
#   answer(auto) → supervisor ─┬─ wiki  (research spoke → evidence; LangGraph planner→solve→auditor)
#                              ├─ dart  (research spoke → findings; tool-calling over the DART MCP)
#                              └─ synthesizer (finalize: one cited answer over all gathered)
# Only the *wiki* StateGraph is a compiled LangGraph; the supervisor hub + DART branch live in
# core.py, so get_graph() can't see them. This script therefore emits BOTH:
#   1. Full architecture (supervisor + spokes) — the source of truth in docs/agent_graph.md
#      (mermaid). The PNG is rendered FROM that block, so they never drift.
#   2. Compiled wiki sub-graph — rendered live from apps.agent.cores.wiki.build (drift check).
#
# Outputs:
#   - ASCII + Mermaid (both views) → terminal (no network)
#   - docs/agent_graph.png   → PNG via mermaid.ink (skipped if this box has no internet)
#
# Usage (from anywhere):
#     scripts/visualize_graph.sh        # render the terminal views + write docs/agent_graph.png
#
set -euo pipefail

cd "$(dirname "$0")/.."                    # repo root (script lives in scripts/)
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

OUT_PNG="docs/agent_graph.png"
ARCH_MD="docs/agent_graph.md"

echo "==> rendering the FULL agent architecture (supervisor + wiki + dart) ..."
"$PY" - "$OUT_PNG" "$ARCH_MD" <<'PY'
import sys
from pathlib import Path

out_png, arch_md = sys.argv[1], sys.argv[2]

# --- 1. Full architecture: the source-of-truth mermaid lives in docs/agent_graph.md, fenced
#        between <!-- full-arch:begin --> / <!-- full-arch:end --> so the docs and the PNG never
#        drift. (The supervisor hub + DART branch aren't in the compiled LangGraph, so there's
#        nothing to introspect — the diagram is authored.)
md = Path(arch_md).read_text(encoding="utf-8")
try:
    block = md.split("<!-- full-arch:begin -->", 1)[1].split("<!-- full-arch:end -->", 1)[0]
    full_mermaid = block.split("```mermaid", 1)[1].rsplit("```", 1)[0].strip()
except IndexError:
    sys.exit(f"!! couldn't find the full-arch:begin/end mermaid block in {arch_md}")

print("\n--- Mermaid (FULL architecture: supervisor + wiki + dart) ---")
print(full_mermaid)

# --- 2. Compiled wiki sub-graph: rendered live from code as a drift check on the wiki half.
print("\n--- Compiled wiki sub-graph (live from apps.agent.cores.wiki.build) ---")
try:
    from apps.agent.cores.wiki import build_app
    from apps.agent.retrieval import INDEX_JSON, load_index

    if not INDEX_JSON.exists():
        print("   (skipped — knowledge/wiki/index.json missing; build the wiki first: "
              "scripts/run_pipeline.sh)")
    else:
        g = build_app(load_index()).get_graph()
        try:
            print(g.draw_ascii())
        except Exception as e:                   # grandalf missing, etc.
            print(f"   (ascii unavailable: {e})")
except Exception as e:                           # import/build failure shouldn't kill the render
    print(f"   (compiled sub-graph unavailable: {type(e).__name__}: {e})")

# --- 3. PNG of the FULL architecture (mermaid.ink — needs internet on THIS box).
try:
    from langchain_core.runnables.graph_mermaid import draw_mermaid_png
    png = draw_mermaid_png(full_mermaid)
    Path(out_png).write_bytes(png)
    print(f"\n--- wrote {out_png} ({len(png)} bytes, full architecture) ---")
except Exception as e:
    print(f"\n   (PNG skipped — no internet to mermaid.ink? {type(e).__name__}: {e})")
PY

echo ""
echo "==> done. View the graph:"
[ -f "$OUT_PNG" ] && echo "    PNG (open in your IDE) : $OUT_PNG"
echo "    mermaid (renders on GitHub) : $ARCH_MD"
