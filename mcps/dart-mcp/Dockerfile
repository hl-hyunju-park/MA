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

# Serve SSE inside the container on 0.0.0.0:8003 (MCP_HOST must be 0.0.0.0 for Docker
# port publishing to work — localhost-only access is enforced host-side by publishing
# `-p 127.0.0.1:8003:8003`, since DART is now consumed in-process by the agent backend).
ENV MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8003

EXPOSE 8003

CMD ["python", "dart.py"]
