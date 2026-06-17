"""Check the running DART MCP server (containerized, SSE) via the fastmcp client.

Unlike test_mcps.py (which spawns dart.py over stdio), this connects to the
already-running networked server the way a real consumer would: the fastmcp
Client over SSE, authenticating with the ?token= URL.

  python mcps/test_fastmcp.py
  DART_MCP_URL=http://123.37.5.219:8002/sse python mcps/test_fastmcp.py   # remote
"""

import asyncio
import os
import re
import sys

from fastmcp import Client

BASE_URL = os.environ.get("DART_MCP_URL", "http://123.37.5.219:8002/sse")
TOKEN = os.environ.get("DART_MCP_TOKEN", "")  # required; no secret baked into source
AUTHED_URL = f"{BASE_URL}?token={TOKEN}"


def _text(result) -> str:
    """Flatten a fastmcp CallToolResult to text."""
    parts = [getattr(c, "text", "") for c in (result.content or [])]
    return " ".join(p for p in parts if p)


# A comma-grouped (or bare) run of >=4 digits, e.g. "485,757,698,000,000".
_NUM = re.compile(r"\d[\d,]{3,}")


def assert_no_inflation(text: str) -> None:
    """Regression guard: the old XBRL bug scaled values 10^6x past float64's
    exact-integer range. Samsung's largest line item is ~15 digits, so any
    19+-digit integer means the scaling bug is back."""
    for tok in _NUM.findall(text):
        assert len(tok.replace(",", "")) <= 18, f"inflated number (scaling bug?): {tok}"


# --- per-tool validators: raise AssertionError on failure, return a short note ---


def v_get_current_date(t: str) -> str:
    t = t.strip()
    assert re.fullmatch(r"\d{8}", t), f"expected YYYYMMDD, got {t!r}"
    return f"date={t}"


def v_search_disclosure(t: str) -> str:
    assert "삼성전자" in t, "company name missing"
    assert "매출액" in t, "expected 매출액 line item"
    assert_no_inflation(t)
    return f"{len(t)} chars, numbers sane"


def v_search_detailed_financial_data(t: str) -> str:
    assert "자산총계" in t and "재무상태표" in t, "expected 재무상태표/자산총계"
    assert_no_inflation(t)
    return f"{len(t)} chars, numbers sane"


def v_search_business_information(t: str) -> str:
    assert len(t) > 200 and "사업" in t, "expected business-overview prose"
    return f"{len(t)} chars of prose"


def v_search_json_financial_data(t: str) -> str:
    assert "자산총계" in t, "expected 자산총계 in JSON BS"
    assert_no_inflation(t)
    return f"{len(t)} chars, numbers sane"


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


async def test_auth_rejected() -> bool:
    """No token -> connection must be refused (401). Returns True on PASS."""
    try:
        async with Client(BASE_URL) as c:  # no ?token=
            await c.list_tools()
        print("  FAIL  auth gate: unauthenticated client connected (expected 401)")
        return False
    except Exception as e:  # noqa: BLE001 - any auth/transport error is the point
        msg = str(e) or type(e).__name__
        print(f"  PASS  auth gate: unauthenticated rejected ({msg[:60]})")
        return True


async def main() -> int:
    print(f"target: {BASE_URL}  (token-authenticated)\n")

    failures = 0

    print("== auth ==")
    if not await test_auth_rejected():
        failures += 1

    print("\n== tools ==")
    async with Client(AUTHED_URL) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        print(f"  discovered {len(names)}: {', '.join(names)}")
        expected = {name for name, _, _ in CASES}
        missing = expected - set(names)
        if missing:
            print(f"  FAIL  missing tools: {missing}")
            failures += 1

        print("\n== per-tool ==")
        for name, args, validate in CASES:
            try:
                res = await client.call_tool(name, args)
                note = validate(_text(res))
                print(f"  PASS  {name}: {note}")
            except AssertionError as e:
                failures += 1
                print(f"  FAIL  {name}: {e}")
            except Exception as e:  # noqa: BLE001
                failures += 1
                print(f"  ERROR {name}: {type(e).__name__}: {str(e)[:200]}")

    total = len(CASES) + 1  # tools + auth
    print(f"\n{total - failures}/{total} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
