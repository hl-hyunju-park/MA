#!/usr/bin/env bash
#
# Normalize a corpus's legacy office formats into the two the pipeline ingests
# (.xlsx via dump_md, .pdf via the vision parser), using LibreOffice headless.
#
#   pptx -> pdf      xls -> xlsx     (see CONVERSIONS in src/stella_kb/convert.py)
#
# Non-destructive + idempotent: the converted file lands next to the original, and a file
# whose target already exists is skipped — so re-running only picks up what's new. Pass
# --replace to delete each source after a verified conversion.
#
# Usage (from anywhere):
#     scripts/run_convert.sh                       # convert the default root (config convert.root)
#     scripts/run_convert.sh --replace             # ... and drop the originals
#     MNA_CONVERT_ROOT=raw/v0.3/data scripts/run_convert.sh
#     scripts/run_convert.sh "raw/v0.3/data" --map doc:docx,xls:xlsx
#
set -euo pipefail

cd "$(dirname "$0")/.."                     # repo root, regardless of caller's cwd
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

: "${MNA_CONVERT_ROOT:=raw/v0.3/data}"
: "${MNA_SOFFICE_BIN:=soffice}"
export MNA_CONVERT_ROOT MNA_SOFFICE_BIN

echo "==> root:    $MNA_CONVERT_ROOT"
echo "==> soffice: $MNA_SOFFICE_BIN"

if [ ! -d "$MNA_CONVERT_ROOT" ]; then
  echo "    !! corpus root not found: $MNA_CONVERT_ROOT  (set MNA_CONVERT_ROOT)"; exit 1
fi
if ! command -v "$MNA_SOFFICE_BIN" >/dev/null 2>&1; then
  echo "    !! '$MNA_SOFFICE_BIN' not on PATH — install LibreOffice or set MNA_SOFFICE_BIN."; exit 1
fi

# Default to actually converting (the module's own default is a dry run); pass --dry-run-only
# upstream by invoking the module directly if you want just the plan.
exec "$PY" -m src.stella_kb.convert "$@" --apply
