#!/usr/bin/env bash
#
# Ingest the v0.3 document data room (the KDB Life DD corpus) into a queryable wiki.
#
#   raw/v0.3/data/**  (nested, mixed-format)
#     → (0) convert legacy formats in place   doc/docx/hwp/pptx/img → pdf, xls → xlsx   [LibreOffice]
#     → (1) curate                            drop bulk/boilerplate per knowledge/v0.3/curate.yaml
#     → (2) spreadsheets → md grids           dump_md.sheet_to_md, full cell fidelity   [no LLM]
#     → (3) pdfs → vision pages               pdf_pages.build_pages                     [needs vLLM]
#     → (4) assemble                          knowledge/v0.3/wiki/{index.json,INDEX.md,pages/}
#     → (5) scaffold curation                 curate_scaffold → decks.yaml + routes.yaml [no LLM]
#     → (6) hierarchical nav                   nav_tree → router.yaml + nav/ + index['nav']  [needs vLLM]
#
# Unlike run_pipeline.sh (the single-workbook formula-model build), this is the document-data-room
# build — it reuses the same wiki pieces but skips the formula DAG (none exists across the ledgers).
# Register the result by adding `v0.3: knowledge/v0.3/wiki` to configs/config.yaml agent.datasets.
#
# Usage (from anywhere):
#     scripts/run_ingest_v03.sh                 # full curated build (convert already done → skipped)
#     scripts/run_ingest_v03.sh --plan          # curation dry-run + counts only (offline)
#     scripts/run_ingest_v03.sh --only "3."     # pilot: just the '3. 계리' section
#     scripts/run_ingest_v03.sh --no-pdf        # spreadsheets only (offline; skip vision)
#     CONVERT=1 scripts/run_ingest_v03.sh       # (re)run the legacy-format conversion first
#
set -euo pipefail

cd "$(dirname "$0")/.."                     # repo root, regardless of caller's cwd
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

export MNA_WIKI_DATA="${MNA_WIKI_DATA:-knowledge/v0.3}"
ROOT="${MNA_CONVERT_ROOT:-raw/v0.3/data}"

# Pass-through: --plan/--no-pdf/--only short-circuit (no vLLM needed for --plan/--no-pdf).
PLAN_OR_OFFLINE=0
for a in "$@"; do [ "$a" = "--plan" ] || [ "$a" = "--no-pdf" ] && PLAN_OR_OFFLINE=1; done

if [ "${CONVERT:-0}" = "1" ]; then
  echo "==> [0] normalizing legacy formats (LibreOffice headless) ..."
  "$PY" -m src.stella_kb.convert "$ROOT" --apply
fi

if [ "$PLAN_OR_OFFLINE" -eq 0 ]; then
  echo "==> [0] checking vLLM endpoint (PDF vision stage needs it) ..."
  if curl -sf --max-time 8 123.37.5.219:8001/v1/models >/dev/null; then
    echo "    vLLM is up"
  else
    echo "    !! vLLM not reachable — run with --no-pdf for the offline spreadsheet build."
    exit 1
  fi
fi

echo "==> building v0.3 wiki  -> $MNA_WIKI_DATA/wiki"
# Pass ROOT explicitly so a no-flag invocation BUILDS (the module's bare-arg __main__ defaults to
# a safe --plan dry-run); --plan/--no-pdf/--only ride along as extra args.
"$PY" -m src.stella_kb.wiki.data_room "$ROOT" "$@"

# [5] Auto-scaffold the curation files from the freshly-built index (overwrites decks.yaml +
# routes.yaml). Skips a --plan dry-run, which writes no index.json. decks.yaml affects only the
# NEXT build (build-time input); routes.yaml is live for the agent immediately.
if [ -f "$MNA_WIKI_DATA/wiki/index.json" ]; then
  echo "==> scaffold curation  -> $MNA_WIKI_DATA/{decks,routes}.yaml"
  "$PY" -m src.stella_kb.wiki.curate_scaffold "$MNA_WIKI_DATA/wiki" --out "$MNA_WIKI_DATA"
fi

# [6] Hierarchical navigation tree (folder summaries) for the drill-down router. Writes
# router.yaml + nav/<folder>/index.md and index['nav']. Folder summaries need the vLLM, so an
# offline build (--no-pdf) gets the tree without summaries; --plan writes no index → skipped.
if [ -f "$MNA_WIKI_DATA/wiki/index.json" ]; then
  NAV_FLAGS=""
  [ "$PLAN_OR_OFFLINE" -eq 0 ] || NAV_FLAGS="--no-summaries"
  echo "==> hierarchical nav  -> $MNA_WIKI_DATA/wiki/router.yaml + nav/"
  "$PY" -m src.stella_kb.wiki.nav_tree "$ROOT" --wiki "$MNA_WIKI_DATA/wiki" $NAV_FLAGS \
    || echo "    !! nav build failed (see above) — agent falls back to the flat index"
fi

if [ "$PLAN_OR_OFFLINE" -eq 0 ] || printf '%s\n' "$@" | grep -q -- '--no-pdf'; then
  echo "==> lint  ($MNA_WIKI_DATA/wiki)"
  "$PY" -m src.stella_kb.wiki.lint "$MNA_WIKI_DATA/wiki" || \
    echo "    !! lint found issues (see above)"
fi

echo "==> done. register it: add 'v0.3: knowledge/v0.3/wiki' to configs/config.yaml agent.datasets"
