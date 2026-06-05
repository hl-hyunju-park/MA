#!/usr/bin/env bash
#
# Rebuild the Project Stella vectorless KB end-to-end, from the workbook to the index.
#
#   data/raw/*_raw.xlsx
#     → data/md/*.md            (1) grid dumps          [mechanical]
#     → data/parsed/*.json      (2) LLM parse pass      [slow, needs vLLM]
#     → data/wiki/pages/*.md    (3) wiki compile        [slow, needs vLLM]
#     → data/wiki/INDEX.md      (4) index / ToC         [mechanical]
#       data/wiki/index.json
#
# Usage (from anywhere):
#     ./run_pipeline.sh            full rebuild
#     ./run_pipeline.sh --no-llm   skip the two LLM stages (reuse existing parsed JSON;
#                                  scaffold-only pages), then rebuild the index
#
set -euo pipefail

cd "$(dirname "$0")/.."                    # repo root (script lives in scripts/)
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

NO_LLM=0
[ "${1:-}" = "--no-llm" ] && NO_LLM=1

if [ "$NO_LLM" -eq 0 ]; then
  echo "==> [0] checking local vLLM endpoint (localhost:33333) ..."
  if curl -sf --max-time 8 localhost:33333/v1/models >/dev/null; then
    echo "    vLLM is up"
  else
    echo "    !! vLLM not reachable — the parse/wiki stages need it."
    echo "       Re-run with --no-llm to rebuild structure + index only."
    exit 1
  fi
fi

echo "==> [1/4] dump sheets to markdown  -> data/md/"
"$PY" -m src.stella_kb.wiki.dump_md --all

if [ "$NO_LLM" -eq 0 ]; then
  echo "==> [2/4] LLM parse pass  -> data/parsed/   [slow]"
  "$PY" -m src.stella_kb.wiki.parse_llm --all

  echo "==> [3/4] compile wiki pages  -> data/wiki/pages/   [slow]"
  "$PY" -m src.stella_kb.wiki.compile --all
else
  echo "==> [2/4] LLM parse pass  -> skipped (--no-llm; reusing data/parsed/)"
  echo "==> [3/4] compile wiki pages  -> data/wiki/pages/   (scaffold only)"
  "$PY" -m src.stella_kb.wiki.compile --all --no-llm
fi

echo "==> [4/4] build index / ToC  -> data/wiki/INDEX.md, index.json"
"$PY" -m src.stella_kb.wiki.index

echo "==> done. entry point: data/wiki/INDEX.md"
