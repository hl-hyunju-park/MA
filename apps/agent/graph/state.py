"""The LangGraph state shared across the planner → router → retriever → verifier →
synthesizer pipeline. Plain dicts only (no langchain message objects); each node builds
its own LLM prompt from these fields, so there is no single growing transcript."""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """Running state threaded through the multi-agent graph."""
    question: str          # the original user question
    index_md: str          # the wiki INDEX (ToC) text, handed to planner/router
    plan: list             # [{"ask": str, "hint_terms": [str, ...]}] from the planner
    cursor: int            # which sub-question (index into plan) is being worked
    pages: list            # page names the router picked for the current sub-question
    tried_pages: list      # pages already read for the current sub-question (retry guard)
    evidence: list         # accumulated [{page, cell, term, value, ask}] across sub-Qs
    answer: str            # the synthesizer's final Korean answer
    trace: list            # per-turn record [{step, agent, action, arg, thought}]
    steps: int             # retriever reads consumed (the budget unit)
    max_steps: int
    retries: int           # verifier→router retries spent on the current sub-question
    route: str             # verifier's conditional-edge decision
    verbose: bool
