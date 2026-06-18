#!/usr/bin/env bash
#
# Template wrapper — copy to scripts/run_<name>.sh and adapt. Matches the house style of
# scripts/run_eval.sh: repo-root cwd, overridable env, pre-flight checks, exec the module.
#
set -euo pipefail

cd "$(dirname "$0")/.."                     # repo root, regardless of caller's cwd
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python

# --- config: surface what the module reads as overridable env (resolved in config.py) -----
: "${SOME_INPUT:=data/v0.1/raw/input.xlsx}"
: "${SOME_OUT_DIR:=data/out}"
export SOME_INPUT SOME_OUT_DIR

echo "==> input:  $SOME_INPUT"
echo "==> output: $SOME_OUT_DIR"

# --- pre-flight: fail fast with a clear message if a prerequisite is missing ---------------
if [ ! -e "$SOME_INPUT" ]; then
  echo "    !! input not found: $SOME_INPUT  (build it first / set SOME_INPUT)"; exit 1
fi
echo "==> checking vLLM endpoint (123.37.5.219:8001) ..."   # drop this block if no LLM needed
if curl -sf --max-time 8 123.37.5.219:8001/v1/models >/dev/null; then
  echo "    vLLM is up"
else
  echo "    !! vLLM not reachable — this step needs it."; exit 1
fi

# --- run: pass through any extra args (e.g. subcommands) -----------------------------------
# replace MODULE with the dotted module path, e.g. src.stella_kb.graph.extract
exec "$PY" -m src.stella_kb.MODULE "$@"
