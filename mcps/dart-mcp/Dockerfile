# DART MCP server, served over the network (SSE) in a container.
# Secrets (DART_API_KEY, DART_MCP_TOKEN) are NOT baked in — pass them at run time
# with `--env-file .env`. dart.py reads them from the environment.
FROM python:3.11-slim

WORKDIR /app

# Runtime deps (mirrors pyproject.toml + the SSE server extras starlette/uvicorn,
# which mcp[cli] pulls in but we pin explicitly for clarity).
RUN pip install --no-cache-dir \
    "mcp[cli]>=1.6.0" \
    "httpx>=0.28.1" \
    "python-dotenv>=1.0.0" \
    "uvicorn>=0.34" \
    "starlette>=0.46"

COPY dart.py ./

# Serve SSE on 0.0.0.0:8002 by default (override via -e at run time).
ENV MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8002

EXPOSE 8002

CMD ["python", "dart.py"]
