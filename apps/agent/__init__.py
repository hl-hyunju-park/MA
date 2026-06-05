"""Wiki query agent — the *query* half of Project Stella, kept separate from the
``src/stella_kb`` *build* half.

``src/stella_kb`` compiles the workbook into the vectorless wiki (``data/wiki/``:
``INDEX.md``, ``index.json``, ``pages/*.md``). This package consumes that wiki at question
time: a LangGraph agent navigates the index and pages to answer M&A valuation questions.
It imports the build library only for the shared LLM client; it never rebuilds the wiki.

Layout:
    tools.py   deterministic wiki access (load_index, lookup, open_page) — no LLM
    graph.py   the LangGraph StateGraph (AgentState, build_app)
    core.py    public API: run / ask / stream_run
    server.py  FastAPI HTTP API (/ask, /ask/stream SSE)
    prompts/   the agent system prompt (Korean-steered)

    from apps.agent import ask
    python -m apps.agent "기업가치는 얼마인가요?"
"""

from .core import ask, run, stream_run

__all__ = ["ask", "run", "stream_run"]
