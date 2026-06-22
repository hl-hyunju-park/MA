#!/usr/bin/env bash
#
# Rebuild the Project Stella vectorless KB end-to-end, from the workbook to the index.
#
#   knowledge/raw/*_raw.xlsx
#     → knowledge/md/*.md            (1) grid dumps          [mechanical]
#     → knowledge/parsed/*.json      (2) LLM parse pass      [needs vLLM; cached -> incremental]
#     → knowledge/wiki/pages/*.md    (3) wiki compile        [needs vLLM; prose cached -> incremental]
#     → knowledge/wiki/INDEX.md      (4) index / ToC         [mechanical]
#       knowledge/wiki/index.json
#   knowledge/raw/*.pdf
#     → knowledge/wiki/pages/FDD*.md (5) PDF ingest + merge  [slow, needs vLLM; skipped if no PDF]
#     → (report)                (6) lint built wiki      [mechanical; broken links / orphans]
#   knowledge/v0.2/raw/*.xlsx (full model)
#     → knowledge/graph/*.json       (7) graph paradigm     [mechanical; semantic graph + page DAG;
#                                                            v0.2 only — reads the canonical workbook]
#
# Stages 2/3/5 cache their LLM calls (.cache/wiki_parse, .cache/wiki_prose, .cache/pdf_structure),
# keyed by content — so an unchanged source is a cache hit (free, deterministic) and only edited
# sheets/decks re-roll. Force a full fresh rebuild by clearing the relevant .cache/ dir first.
#
# Usage (from anywhere):
#     ./run_pipeline.sh            full rebuild
#     ./run_pipeline.sh --no-llm   skip the three LLM stages (reuse existing parsed JSON;
#                                  scaffold-only pages; no PDF re-ingest), then rebuild index
#
set -euo pipefail

cd "$(dirname "$0")/.."                    # repo root (script lives in scripts/)
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

NO_LLM=0
[ "${1:-}" = "--no-llm" ] && NO_LLM=1

if [ "$NO_LLM" -eq 0 ]; then
  echo "==> [0] checking vLLM endpoint (123.37.5.219:8001) ..."
  if curl -sf --max-time 8 123.37.5.219:8001/v1/models >/dev/null; then
    echo "    vLLM is up"
  else
    echo "    !! vLLM not reachable — the parse/wiki stages need it."
    echo "       Re-run with --no-llm to rebuild structure + index only."
    exit 1
  fi
fi

echo "==> [1/7] dump sheets to markdown  -> knowledge/md/"
"$PY" -m src.stella_kb.wiki.dump_md --all

if [ "$NO_LLM" -eq 0 ]; then
  echo "==> [2/7] LLM parse pass  -> knowledge/parsed/   [slow]"
  "$PY" -m src.stella_kb.wiki.parse_llm --all

  echo "==> [3/7] compile wiki pages  -> knowledge/wiki/pages/   [slow]"
  "$PY" -m src.stella_kb.wiki.compile --all
else
  echo "==> [2/7] LLM parse pass  -> skipped (--no-llm; reusing knowledge/parsed/)"
  echo "==> [3/7] compile wiki pages  -> knowledge/wiki/pages/   (scaffold only)"
  "$PY" -m src.stella_kb.wiki.compile --all --no-llm
fi

echo "==> [4/7] build index / ToC  -> knowledge/wiki/INDEX.md, index.json"
"$PY" -m src.stella_kb.wiki.index

if [ "$NO_LLM" -eq 0 ]; then
  echo "==> [5/7] PDF ingest + merge into index  -> knowledge/wiki/pages/FDD*.md   [slow]"
  "$PY" -m src.stella_kb.wiki.pdf_pages          # self-skips if no knowledge/raw/*.pdf
else
  echo "==> [5/7] PDF ingest  -> skipped (--no-llm; existing FDD pages left as-is)"
fi

DATA_VER="${MNA_WIKI_DATA:-knowledge/v0.2}"
WIKI_DIR="$DATA_VER/wiki"
echo "==> [6/7] lint the built wiki  ($WIKI_DIR)"
"$PY" -m src.stella_kb.wiki.lint "$WIKI_DIR" || \
  echo "    !! lint found error-severity issues (see above) — build left in place for inspection"

# Graph paradigm: formula DAG -> semantic graph + page DAG. Mechanical (openpyxl + networkx,
# no vLLM), so it runs even under --no-llm. It reads the canonical v0.2 workbook (FULL_WORKBOOK),
# so it only makes sense for the v0.2 build — skip for other (e.g. PDF-only) versions.
echo "==> [7/7] build graph paradigm  -> knowledge/graph/{stella_graph,stella_pages}.json"
if [ "$DATA_VER" = "knowledge/v0.2" ]; then
  "$PY" -m src.stella_kb.graph.semantic     # semantic graph + page DAG (stella_pages.json)
  "$PY" -m src.stella_kb.graph.viz pages    # render the page DAG -> frontend/web/graph_pages.html
else
  echo "    skipped — graph paradigm reads the canonical v0.2 workbook only (got $DATA_VER)"
fi

echo "==> done. entry point: $WIKI_DIR/INDEX.md"
