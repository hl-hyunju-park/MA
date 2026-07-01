#!/usr/bin/env bash
# Serve gemma-4-31B-it via vLLM (docker) WITH tool-calling enabled.
#
# Why this exists: the shared guest vLLM on :33333 was launched without
# tool-calling, so any agent that binds tools (LangGraph create_react_agent,
# the dart-mcp agent test) gets HTTP 400. This stands up our own instance with
# --enable-auto-tool-choice so the full MCP agent loop can run.
#
# GPUs 2,3,4,5 (TP=4), host port 8001, model cache at /data/.cache (already pulled).
# Point clients at  http://localhost:8001/v1  (model name: gemma-4-31B-it).
#
# Usage:
#   scripts/serve_gemma.sh            # foreground
#   PORT=8002 GPUS=2,3 scripts/serve_gemma.sh
set -euo pipefail

MODEL="${MODEL:-google/gemma-4-31B-it}"
SERVED_NAME="${SERVED_NAME:-gemma-4-31B-it}"
IMAGE="${IMAGE:-vllm-openai:v0.19.0-gemma4}"   # purpose-built gemma-4 image on this box
PORT="${PORT:-8001}"                            # :33333=guest gemma, :8000=project API
GPUS="${GPUS:-2,3,4,5}"                             # free A100s; TP size derived below
HF_CACHE="${HF_CACHE:-/data/.cache}"            # HF hub cache (models-- live here directly)
NAME="${NAME:-hj-gemma4-tools}"
# Tool-call parser. This gemma-4 image emits its native
# `<|tool_call>call:name{args}<tool_call|>` format, parsed by the bundled
# 'gemma4' parser (vllm/tool_parsers/gemma4_tool_parser.py). 'pythonic' does
# NOT match it — it leaves the call in message content with finish_reason=stop,
# so the agent never executes a tool. List names: ls in the image's
# /usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/.
PARSER="${PARSER:-gemma4}"

# tensor-parallel size = number of GPUs listed
TP="$(awk -F, '{print NF}' <<<"$GPUS")"

exec docker run --rm \
  --runtime nvidia \
  --gpus "\"device=${GPUS}\"" \
  -v "${HF_CACHE}:${HF_CACHE}" \
  -e "HF_HUB_CACHE=${HF_CACHE}" \
  -p "${PORT}:8000" \
  --ipc=host \
  --name "${NAME}" \
  "${IMAGE}" \
  --model "${MODEL}" \
  --served-model-name "${SERVED_NAME}" \
  --tensor-parallel-size "${TP}" \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice \
  --tool-call-parser "${PARSER}"
