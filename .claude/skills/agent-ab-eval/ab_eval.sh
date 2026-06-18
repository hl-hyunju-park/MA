#!/usr/bin/env bash
#
# A/B an agent-only change on a FIXED built wiki. Each arg is  name=ENV_PIN  where ENV_PIN is a
# single "VAR=value" env override applied for that arm, or "-" for the baseline/default config.
# Runs each arm RUNS times (eval only, sequential — no vLLM contention), then judges every set.
#
#   AB_DIR=data/eval/ab RUNS=2 EVAL_DATASET=v0.2 \
#     ab_eval.sh off='MNA_AGENT_ROUTES=/tmp/routes_off.yaml' on='-'
#
set -uo pipefail
cd "$(dirname "$0")/../../.."                # repo root (skill is .claude/skills/<name>/)
PY="${PY:-.venv/bin/python}"; [ -x "$PY" ] || PY=python
export PYTHONUNBUFFERED=1
: "${AB_DIR:=data/eval/ab}"
: "${RUNS:=2}"
export EVAL_DATASET="${EVAL_DATASET:-v0.2}"

echo "==> checking vLLM endpoint (123.37.5.219:8001) ..."
curl -sf --max-time 8 123.37.5.219:8001/v1/models >/dev/null || { echo "    !! vLLM down"; exit 1; }

mkdir -p "$AB_DIR"   # the per-run dirs are made by qa_eval, but the "$dir.log" redirect needs AB_DIR first

run_one () {  # arm_name  env_pin  run_idx
  local name="$1" pin="$2" r="$3" dir="$AB_DIR/${1}_r${3}"
  echo "=== EVAL ${name} run${r} (pin=${pin}) ==="
  if [ "$pin" = "-" ]; then
    EVAL_OUT_DIR="$dir" "$PY" -m eval.qa_eval eval > "$dir.log" 2>&1
  else
    env "$pin" EVAL_OUT_DIR="$dir" "$PY" -m eval.qa_eval eval > "$dir.log" 2>&1
  fi
  local n err
  n=$("$PY" -c "import json;print(len(json.load(open('$dir/answers.json'))))" 2>/dev/null || echo 0)
  err=$(grep -c '\[ERROR\]' "$dir/answers.json" 2>/dev/null || echo '?')
  echo "    ${name} run${r}: ${n} answers, ${err} errors"
  [ "$err" != "0" ] && echo "    !! ${err} errors (likely vLLM timeouts) — consider re-running this arm"
}

dirs=()
for r in $(seq 1 "$RUNS"); do
  for spec in "$@"; do
    name="${spec%%=*}"; pin="${spec#*=}"
    run_one "$name" "$pin" "$r"
    dirs+=("${name}_r${r}")
  done
done

for d in "${dirs[@]}"; do
  echo "=== JUDGE $d ==="
  EVAL_OUT_DIR="$AB_DIR/$d" "$PY" -m eval.qa_eval judge >> "$AB_DIR/$d.log" 2>&1
done
echo "=== ALL DONE — analyze with ab_analyze.py $AB_DIR <armA> <armB> ==="
