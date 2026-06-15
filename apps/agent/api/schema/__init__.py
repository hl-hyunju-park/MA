"""Pydantic request/response models for the agent HTTP API (``apps.agent.api.server``).

Kept separate from the route handlers so the wire contract is in one place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(..., description="KO/EN question about the Centroid valuation or a public company.")
    max_steps: int = Field(3, ge=1, le=20, description="Per-branch read budget (initial read + retries).")
    include_trace: bool = Field(True, description="Return the routing trace.")
    source: Literal["auto", "wiki", "dart"] = Field(
        "auto", description="Backend: auto-route, 'wiki' (Centroid KB), or 'dart' (public co. via DART)."
    )


class TraceStep(BaseModel):
    step: int
    agent: str  # which pipeline agent ran: planner|router|retriever|verifier|synthesizer
    action: str
    arg: str
    thought: str


class AskResponse(BaseModel):
    question: str
    answer: str
    steps: int
    source: str = "wiki"  # which backend answered: wiki | dart
    trace: list[TraceStep] | None = None


__all__ = ["AskRequest", "AskResponse", "TraceStep"]
