#!/usr/bin/env bash
#
# Diff two eval runs to explain WHY items changed score (the regression debugger).
# Reuses eval/diff_runs.py — joins each run's answers.json + scores.json and, for every
# item whose score moved, prints the delta in pages_opened / evidence / router_paths. This
# is how an A/B that "washed" (net Δ≈0) is decomposed into the items it lifted vs. regressed.
#
# Usage (from anywhere):
#     scripts/run_diff.sh knowledge/eval/v0.2_now_1 knowledge/eval/v0.2_now_2
#     scripts/run_diff.sh <baseline_dir> <treatment_dir> --all     # also list unchanged
#
# Offline + deterministic (no vLLM, no network) — it only reads the two runs' JSON.
set -euo pipefail

cd "$(dirname "$0")/.."                    # repo root, regardless of caller's cwd
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

exec "$PY" -m eval.diff_runs "$@"
