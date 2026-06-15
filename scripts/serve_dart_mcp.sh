#!/usr/bin/env bash
# Serve the DART MCP server over the network (SSE) so a few specific people can
# share ONE running instance. Uses the server-side DART_API_KEY (from
# mcps/dart-mcp/.env) for every caller, and gates access with DART_MCP_TOKEN
# (also in .env) — clients must send `Authorization: Bearer <token>`.
#
# Default stays stdio for local use (test_mcps.py); this script forces SSE.
#
# Usage:
#   scripts/serve_dart_mcp.sh                 # SSE on :8002
#   MCP_PORT=9002 scripts/serve_dart_mcp.sh
set -euo pipefail

DIR="/data/hjpark10/MA/mcps/dart-mcp"
export MCP_TRANSPORT=sse
export MCP_HOST="${MCP_HOST:-0.0.0.0}"
export MCP_PORT="${MCP_PORT:-8002}"

# DART_API_KEY and DART_MCP_TOKEN are loaded from .env by dart.py (load_dotenv()).
exec uv --directory "$DIR" run dart.py
