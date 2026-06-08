"""The LangGraph state shared across the planner → router → retriever → verifier →
synthesizer pipeline. Plain dicts only (no langchain message objects); each node builds
its own LLM prompt from these fields, so there is no single growing transcript."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

# Two channels accumulate monotonically across the run — every node appends and nothing
# ever resets them — so they carry an ``operator.add`` reducer: a node returns ONLY its
# new items and LangGraph concatenates. The other list fields (``pages``/``tried_pages``)
# are reset per sub-question, so they keep the default overwrite reducer (manual lists).


class AgentState(TypedDict, total=False):
    """Running state threaded through the multi-agent graph."""
    question: str          # the original user question
    index_md: str          # the wiki INDEX (ToC) text, handed to planner/router
    plan: list             # [{"ask": str, "hint_terms": [str, ...]}] from the planner
    cursor: int            # which sub-question (index into plan) is being worked
    pages: list            # page names the router picked for the current sub-question
    tried_pages: list      # pages already read for the current sub-question (retry guard)
    evidence: Annotated[list, operator.add]  # accumulated [{page, cell, term, value, ask}]
    paths: Annotated[list, operator.add]     # provenance chains [{ask, direction, chain:[...]}]
    answer: str            # the synthesizer's final Korean answer
    trace: Annotated[list, operator.add]     # per-turn record [{step, agent, action, arg, thought}]
    steps: int             # retriever reads consumed (the budget unit)
    max_steps: int
    retries: int           # verifier→router retries spent on the current sub-question
    route: str             # verifier's conditional-edge decision
    verbose: bool
