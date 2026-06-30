"""Deterministic offline tests for the DART tool-calling backend (no live SSE / no LLM).

The real backend (`apps/agent/cores/dart.py`) connects to the DART MCP server over SSE and drives a
LangChain `create_agent` tool-calling loop on the gemma-4 tool LLM. Here the three lazy imports
(`create_agent` / `MultiServerMCPClient` / `ChatOpenAI`) are patched with fakes so we exercise the
real `_arun` orchestration, the trace rendering, the gemma channel-token stripping, and the
never-raises error contract — without touching the network. The live run is the module `__main__`.
"""

from __future__ import annotations

import asyncio

from apps.agent.cores import dart


# --- pure helpers ----------------------------------------------------------------------

def test_clean_strips_gemma_channel_tokens():
    # gemma-4 leaks "<|channel>thought\n<channel|>" into content; only prose should survive
    assert dart._clean("<|channel>thought\n<channel|>오늘 날짜는 2026년입니다.") == "오늘 날짜는 2026년입니다."
    assert dart._clean("<|channel>analysis<channel|>삼성전자 공시입니다.") == "삼성전자 공시입니다."
    assert dart._clean("순수 텍스트") == "순수 텍스트"      # untouched when no tokens
    assert dart._clean(None) == ""                          # tolerates None


def test_short_args_caps_and_formats():
    assert dart._short_args({"corp": "삼성전자", "year": 2024}) == "corp=삼성전자, year=2024"
    assert dart._short_args(["raw", "list"]) == "['raw', 'list']"   # non-dict → str
    assert len(dart._short_args({"k": "x" * 500})) <= 120           # capped


# --- trace rendering -------------------------------------------------------------------

class _AI:
    """Stand-in for a LangChain AI message: optional tool_calls, string content."""
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class ToolMessage:                       # name matters: _trace_from keys on __class__.__name__
    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.tool_calls = []


def test_trace_from_renders_calls_and_results_sequentially():
    msgs = [
        _AI(tool_calls=[{"name": "search_disclosures", "args": {"corp": "삼성전자"}}]),
        ToolMessage("search_disclosures", "공시 3건: 사업보고서 …"),
        _AI(content="삼성전자의 최근 공시는 …"),
    ]
    trace = dart._trace_from(msgs)
    assert [e["action"] for e in trace] == ["call", "result"]
    assert [e["step"] for e in trace] == [0, 1]                 # sequential
    assert all(e["agent"] == "dart" for e in trace)
    assert "search_disclosures(corp=삼성전자)" == trace[0]["arg"]
    assert trace[1]["arg"].startswith("search_disclosures: 공시 3건")


# --- _arun orchestration (mocked agent stack) ------------------------------------------

def _install_fake_stack(monkeypatch, *, final_content, token="tok"):
    """Patch the three lazy imports in dart._arun with offline fakes; return nothing."""
    class FakeClient:
        def __init__(self, cfg):
            self.cfg = cfg
        async def get_tools(self):
            return []

    class FakeChat:
        def __init__(self, **kw):
            self.kw = kw

    def fake_create_agent(model, tools):
        class _Agent:
            async def ainvoke(self, inp):
                return {"messages": [
                    _AI(tool_calls=[{"name": "search_disclosures", "args": {"corp": "삼성전자"}}]),
                    ToolMessage("search_disclosures", "결과 데이터"),
                    _AI(content=final_content),
                ]}
        return _Agent()

    monkeypatch.setattr("langchain.agents.create_agent", fake_create_agent)
    monkeypatch.setattr("langchain_mcp_adapters.client.MultiServerMCPClient", FakeClient)
    monkeypatch.setattr("langchain_openai.ChatOpenAI", FakeChat)
    monkeypatch.setattr(dart, "DART_MCP_TOKEN", token)


def test_arun_happy_path_cleans_answer_and_counts_steps(monkeypatch):
    _install_fake_stack(monkeypatch, final_content="<|channel>final<channel|>삼성전자 공시 요약입니다.")
    out = asyncio.run(dart._arun("삼성전자 공시 알려줘"))
    assert out["answer"] == "삼성전자 공시 요약입니다."     # channel tokens stripped
    assert out["steps"] == 1                                # one tool call
    assert [e["action"] for e in out["trace"]] == ["call", "result"]


def test_arun_empty_answer_placeholder(monkeypatch):
    _install_fake_stack(monkeypatch, final_content="")
    assert asyncio.run(dart._arun("q"))["answer"] == "(빈 답변)"


def test_arun_missing_token_raises(monkeypatch):
    monkeypatch.setattr(dart, "DART_MCP_TOKEN", "")
    try:
        asyncio.run(dart._arun("q"))
        assert False, "expected RuntimeError on missing token"
    except RuntimeError as e:
        assert "DART_MCP_TOKEN" in str(e)


# --- never-raises error contract -------------------------------------------------------

def test_arun_safe_wraps_errors_into_answer(monkeypatch):
    async def boom(q):
        raise RuntimeError("MCP down")
    monkeypatch.setattr(dart, "_arun", boom)
    out = asyncio.run(dart.arun_safe("q"))
    assert "RuntimeError" in out["answer"] and "MCP down" in out["answer"]
    assert out["trace"] == [] and out["steps"] == 0


def test_run_dart_wraps_errors_into_answer(monkeypatch):
    async def boom(q):
        raise ValueError("token bad")
    monkeypatch.setattr(dart, "_arun", boom)
    out = dart.run_dart("q")                       # sync entry, must not raise
    assert "ValueError" in out["answer"] and out["steps"] == 0
