"""Deterministic offline tests for the /ask/stream SSE endpoint (no live vLLM / no built wiki).

The endpoint (`apps/agent/api/server.py::ask_stream`) consumes `core.astream_run` and SSE-encodes
each event. Here the live-vLLM probe (`_require_llm`), the dataset resolver (`_resolve_store`), and
the event source (`astream_run`) are stubbed, so we drive the real FastAPI route via `TestClient`
and assert the SSE framing — token chunks join to the final answer, the stream terminates with
`done`, a mid-stream error surfaces in-band as `event: error` (not a 500), and a blank question is
rejected before any work. `TestClient(app)` is created WITHOUT the context manager so the lifespan
(which requires a built default dataset) does not run.
"""

from __future__ import annotations

import types

from fastapi.testclient import TestClient

from apps.agent.api import server


def _events(sse_text: str) -> list[tuple[str, str]]:
    """Parse raw SSE text into ``[(event, data)]`` frames."""
    out = []
    for block in sse_text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if ev is not None:
            out.append((ev, data or ""))
    return out


def _patch_common(monkeypatch):
    async def _ok():
        return None
    monkeypatch.setattr(server, "_require_llm", _ok)
    monkeypatch.setattr(server, "_resolve_store",
                        lambda ds: types.SimpleNamespace(dataset=ds or "v0.1"))


def test_ask_stream_joins_tokens_into_answer(monkeypatch):
    _patch_common(monkeypatch)

    async def fake_stream(question, max_steps=None, source="auto", store=None):
        yield {"type": "step", "agent": "supervisor", "detail": "deciding"}
        yield {"type": "token", "text": "기업가치는 "}
        yield {"type": "token", "text": "206,131입니다."}
        yield {"type": "answer", "answer": "기업가치는 206,131입니다.", "steps": 1, "sources": []}
    monkeypatch.setattr(server, "astream_run", fake_stream)

    resp = TestClient(server.app).get("/ask/stream?question=기업가치는?")
    assert resp.status_code == 200
    frames = _events(resp.text)
    kinds = [e for e, _ in frames]
    assert "step" in kinds and frames[-1][0] == "done"

    import json
    tokens = "".join(json.loads(d)["text"] for e, d in frames if e == "token")
    answer = next(json.loads(d)["answer"] for e, d in frames if e == "answer")
    assert tokens == answer == "기업가치는 206,131입니다."


def test_ask_stream_surfaces_midstream_error_inband(monkeypatch):
    _patch_common(monkeypatch)

    async def boom_stream(question, max_steps=None, source="auto", store=None):
        yield {"type": "token", "text": "부분 답변"}
        raise RuntimeError("retriever exploded")
    monkeypatch.setattr(server, "astream_run", boom_stream)

    resp = TestClient(server.app).get("/ask/stream?question=x")
    assert resp.status_code == 200                      # SSE error is in-band, not a 500
    frames = _events(resp.text)
    assert ("error" in [e for e, _ in frames])
    assert any("retriever exploded" in (d or "") for e, d in frames if e == "error")


def test_ask_stream_blank_question_422(monkeypatch):
    _patch_common(monkeypatch)
    # the empty-question guard fires before _require_llm / astream_run, so no stub needed there
    resp = TestClient(server.app).get("/ask/stream?question=%20")
    assert resp.status_code == 422
