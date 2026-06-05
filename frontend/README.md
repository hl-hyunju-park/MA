# Project Stella — Web frontend

React + TypeScript (Vite) chat UI for the wiki query agent. Talks to the FastAPI
backend (`apps/agent/api`) over its REST + SSE endpoints; every answer is rendered with
its `Sheet!Cell` provenance and a collapsible **추론 과정** (routing trace) showing which
wiki pages the agent opened and why.

## Run (dev)

The frontend is a separate dev server that proxies API calls to the backend, so start
both:

```bash
# 1. backend (from repo root, venv active) — serves :8000
scripts/run_server.sh                 # or: .venv/bin/uvicorn apps.agent.api.server:app --port 8000

# 2. frontend — serves :5173, proxies /ask /ask/stream /health -> :8000
cd frontend
npm install        # one-time
npm run dev        # http://localhost:5173  (add -- --host to expose on the network)
```

Open http://localhost:5173. The proxy (see `vite.config.ts`) means the browser only ever
talks to `5173` — no CORS. Point at a non-default backend with a `.env`:
`VITE_API_TARGET=http://host:port`.

## Build (prod)

```bash
npm run build      # tsc --noEmit + vite build -> frontend/dist/
npm run preview    # serve the built bundle locally
```

`dist/` is a static bundle; serve it with any static host, or behind the FastAPI app.

## Layout

```
frontend/
  index.html              # Vite entry
  vite.config.ts          # dev proxy to the FastAPI backend
  src/
    main.tsx              # React root
    App.tsx               # chat state + SSE orchestration
    api.ts                # typed REST/SSE client (mirrors apps/agent/api/schema)
    format.tsx            # highlight Sheet!Cell refs inline
    styles.css            # dark finance theme
    components/
      StatusBadge.tsx     # backend/LLM health pill (polls /health)
      Composer.tsx        # auto-resizing input (Enter=send, Shift+Enter=newline)
      ChatMessage.tsx     # a user/bot turn
      TracePanel.tsx      # collapsible routing trace
  web/                    # zero-build single-file HTML fallback (served by FastAPI at /ui)
```

`web/index.html` is a dependency-free fallback the backend serves directly at `/` and
`/ui` — handy when Node isn't available. The React app here is the primary UI.
