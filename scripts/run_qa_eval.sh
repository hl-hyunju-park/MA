#!/usr/bin/env bash
#
# Evaluate the wiki agent on the v0.2 vision-QA ground-truth set (rubric-based judge).
# Reuses eval/qa_eval.py — runs the 54 STELLA/CAESAR/LIFE FDD questions through the agent
# against a prebuilt wiki (default the v0.2 dataset), then LLM-judges each against its rubric.
#
# Usage (from anywhere):
#     scripts/run_qa_eval.sh                     # eval + judge -> knowledge/eval_v0.2_qa
#     scripts/run_qa_eval.sh judge               # re-judge existing answers only
#     EVAL_DATASET=default scripts/run_qa_eval.sh # score a different built dataset
#
set -euo pipefail

cd "$(dirname "$0")/.."                    # repo root, regardless of caller's cwd
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

export EVAL_DATASET="${EVAL_DATASET:-v0.2}"
export EVAL_QA="${EVAL_QA:-test_data/v0.2/ground_truth/qa.jsonl}"
export EVAL_OUT_DIR="${EVAL_OUT_DIR:-knowledge/eval/v0.2}"
CMDS="${*:-eval judge}"

echo "==> dataset (target wiki): $EVAL_DATASET"
if [ ! -f "$EVAL_QA" ]; then
  echo "    !! question set not found: $EVAL_QA"
  exit 1
fi
echo "==> questions: $EVAL_QA ($(grep -c . "$EVAL_QA" | tr -d ' ') Q)"
echo "==> output:    $EVAL_OUT_DIR  (answers.json · scores.json · report.md)"

echo "==> checking vLLM endpoint (123.37.5.219:8001) ..."
if curl -sf --max-time 8 123.37.5.219:8001/v1/models >/dev/null; then
  echo "    vLLM is up"
else
  echo "    !! vLLM not reachable — the agent run and the judge both need it."
  exit 1
fi

echo "==> running: qa_eval $CMDS"
exec "$PY" -m eval.qa_eval $CMDS
