"""Tests for the DART MCP server.

Two layers:
  1. Per-tool tests (default) — each of the 5 dart-mcp tools is called directly
     over MCP with valid args and its output is asserted. Deterministic, no LLM.
     Includes a regression guard against the XBRL number-inflation bug (values
     were once scaled 10^6x past float64's integer range).
  2. Agent e2e (--agent) — the full tool-calling loop against the gemma-4
     endpoint on :8001 (needs that server up; see scripts/serve_gemma.sh).

Run:
  python mcps/test_mcps.py            # per-tool tests only
  python mcps/test_mcps.py --agent    # also run the full agent loop
"""

import argparse
import asyncio
import re
import sys
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent


from langchain_mcp_adapters.client import MultiServerMCPClient

DART = {
    "dart": {
        "transport": "stdio",
        "command": "uv",
        "args": [
            "--directory",
            "/data/hjpark10/MA/mcps/dart-mcp",
            "run",
            "dart.py",
        ],
    }
}

LLM_BASE_URL = "http://123.37.5.219:8001/v1"
LLM_MODEL = "gemma-4-31B-it"

TOOL_TIMEOUT = 120  # seconds per tool call (XBRL fetches are slow)


def _text(out) -> str:
    """Flatten an MCP tool result (list of content parts, or str) to text."""
    if isinstance(out, list):
        return " ".join(p.get("text", "") for p in out if isinstance(p, dict))
    return str(out)


# A comma-grouped (or bare) run of >=4 digits, e.g. "485,757,698,000,000".
_NUM = re.compile(r"\d[\d,]{3,}")


def assert_no_inflation(text: str) -> None:
    """Regression guard for the format_numeric_value bug.

    XBRL fact values were wrongly rescaled by 10**-decimals, inflating amounts
    ~10^6x and corrupting them past float64's exact-integer range (2^53). Even
    Samsung's largest line item (자산총계 ~485조 = 15 digits) stays well under 18
    digits, so any 19+-digit integer means the scaling bug is back.
    """
    for tok in _NUM.findall(text):
        digits = tok.replace(",", "")
        assert len(digits) <= 18, f"inflated number (scaling bug?): {tok}"


# --- per-tool validators: raise AssertionError on failure, return a short note ---


def v_get_current_date(t: str) -> str:
    t = t.strip()
    assert re.fullmatch(r"\d{8}", t), f"expected YYYYMMDD, got {t!r}"
    return f"date={t}"


def v_search_disclosure(t: str) -> str:
    assert "삼성전자" in t, "company name missing from output"
    assert "매출액" in t, "expected 매출액 line item"
    assert_no_inflation(t)
    return f"{len(t)} chars, 매출액 present, numbers sane"


def v_search_detailed_financial_data(t: str) -> str:
    assert "자산총계" in t, "expected 자산총계 in 재무상태표"
    assert "재무상태표" in t, "expected 재무상태표 section"
    assert_no_inflation(t)
    return f"{len(t)} chars, 자산총계 present, numbers sane"


def v_search_business_information(t: str) -> str:
    assert len(t) > 200, f"business text too short ({len(t)} chars)"
    assert "사업" in t, "expected business-overview prose"
    return f"{len(t)} chars of business prose"


def v_search_json_financial_data(t: str) -> str:
    assert "자산총계" in t, "expected 자산총계 in JSON BS"
    assert_no_inflation(t)
    return f"{len(t)} chars, 자산총계 present, numbers sane"


# tool name -> (args, validator)
CASES = [
    ("get_current_date", {}, v_get_current_date),
    (
        "search_disclosure",
        {"company_name": "삼성전자", "start_date": "20240101", "end_date": "20240630"},
        v_search_disclosure,
    ),
    (
        "search_detailed_financial_data",
        {"company_name": "삼성전자", "start_date": "20240101", "end_date": "20240630", "statement_type": "재무상태표"},
        v_search_detailed_financial_data,
    ),
    (
        "search_business_information",
        {
            "company_name": "삼성전자",
            "start_date": "20240101",
            "end_date": "20240630",
            "information_type": "사업의 개요",
        },
        v_search_business_information,
    ),
    (
        "search_json_financial_data",
        {"company_name": "삼성전자", "bsns_year": "2023", "statement_type": "BS"},
        v_search_json_financial_data,
    ),
]


async def run_tool_tests(tools: dict) -> int:
    """Run every per-tool test. Returns the count of failures."""
    expected = {name for name, _, _ in CASES}
    missing = expected - set(tools)
    assert not missing, f"server did not expose tools: {missing}"

    failures = 0
    for name, args, validate in CASES:
        try:
            out = await asyncio.wait_for(tools[name].ainvoke(args), timeout=TOOL_TIMEOUT)
            note = validate(_text(out))
            print(f"  PASS  {name}: {note}")
        except AssertionError as e:
            failures += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:  # noqa: BLE001 - report any tool/transport error
            failures += 1
            print(f"  ERROR {name}: {type(e).__name__}: {str(e)[:200]}")
    return failures


async def run_agent(tools_list) -> None:
    """Full tool-calling loop against the gemma-4 endpoint (needs :8001 up)."""

    llm = ChatOpenAI(model=LLM_MODEL, base_url=LLM_BASE_URL, api_key="EMPTY")
    agent = create_agent(model=llm, tools=tools_list)
    result = await agent.ainvoke({"messages": [("user", "삼성전자 공시 알려줘")]})
    for m in result["messages"]:
        m.pretty_print()


async def main(run_agent_loop: bool) -> int:
    client = MultiServerMCPClient(DART)

    tools_list = await client.get_tools()
    tools = {t.name: t for t in tools_list}
    print(f"loaded {len(tools_list)} tools: {', '.join(sorted(tools))}\n")
    assert tools, "no tools loaded from the dart MCP server"

    # print("== per-tool tests ==")
    # failures = await run_tool_tests(tools)
    # total = len(CASES)
    # print(f"\n{total - failures}/{total} tools passed.")

    # if run_agent_loop:
    print("\n== agent e2e (삼성전자 공시 알려줘) ==")
    await run_agent(tools_list)

    return 1
    # return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", action="store_true", help="also run the full tool-calling agent loop (needs :8001)")
    ns = parser.parse_args()
    sys.exit(asyncio.run(main(ns.agent)))
