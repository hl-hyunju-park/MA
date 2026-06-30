#!/usr/bin/env bash
# Serve the DART MCP server over SSE for the in-process agent backend (apps/agent
# cores/dart.py) to consume on localhost. Uses the server-side DART_API_KEY (from
# mcps/dart-mcp/.env) for every caller, and gates access with DART_MCP_TOKEN
# (also in .env) — clients must send `Authorization: Bearer <token>`.
#
# Binds to 127.0.0.1:8003 by default — localhost-only, since DART is now called
# within the agent server rather than shared over the network. (Public :8002 is
# freed for the embedding server.) Set MCP_HOST=0.0.0.0 to share off-box again.
#
# Default stays stdio for local use (test_mcps.py); this script forces SSE.
#
# Usage:
#   scripts/serve_dart_mcp.sh                 # SSE on 127.0.0.1:8003
#   MCP_HOST=0.0.0.0 MCP_PORT=8002 scripts/serve_dart_mcp.sh
set -euo pipefail

DIR="/data/hjpark10/MA/mcps/dart-mcp"
export MCP_TRANSPORT=sse
export MCP_HOST="${MCP_HOST:-127.0.0.1}"
export MCP_PORT="${MCP_PORT:-8003}"

# DART_API_KEY and DART_MCP_TOKEN are loaded from .env by dart.py (load_dotenv()).
exec uv --directory "$DIR" run dart.py
