"""Shared engine for the wiki pipeline personas (planner/solve/audit/synthesize).

Holds the one-LLM-call helper and the in-flight cap every persona shares: ``_ask`` (system+user
→ parsed JSON action + raw), guarded by ``_LLM_SEM`` so no more than ``STELLA_FANOUT`` (default 4)
requests hit the shared vLLM at once. ``set_fanout`` rebinds ``_FANOUT``/``_LLM_SEM`` at runtime;
callers reach these as ``engine._FANOUT`` / ``engine._LLM_SEM`` (module-qualified) so the rebind is
picked up at call time. Also the loaded prompt constants and the small pure helpers (``_rec``,
``_per``, ``_cell_on_page``, ``parse_action``).

The deterministic wiki reads live in ``apps.agent.retrieval``; the LLMs here only route and write
prose. The shared vLLM has no native tool-calling, hence the JSON-per-turn (ReAct-style) contract.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading

from src.stella_kb import config
from src.stella_kb.llm import chat

from ...prompts import load as load_prompt

log = logging.getLogger("apps.agent.wiki")


def _debug() -> bool:
    """Verbose per-call agent logging, gated on ``MNA_AGENT_DEBUG`` (off → silent, no overhead)."""
    return os.environ.get("MNA_AGENT_DEBUG", "").lower() in ("1", "true", "yes", "on")

PLANNER = load_prompt("planner")
ROUTER = load_prompt("router")
RETRIEVER = load_prompt("retriever")
VERIFIER = load_prompt("verifier")
SYNTHESIZER = load_prompt("synthesizer")

_FANOUT = max(1, config.agent_fanout())  # concurrent LLM requests cap
_LLM_SEM = threading.Semaphore(_FANOUT)  # guards the shared guest vLLM from overload
_SYNTH_ORDER = 10**9  # sorts the synthesizer's trace entry last, after every branch


def set_fanout(n: int) -> None:
    """Resize the in-flight LLM cap. The library default (4) is deliberately polite to the
    shared guest vLLM; batch jobs (e.g. the eval, which fans out many questions at once) can
    raise it to match their worker count so workers aren't all blocked on a 4-slot semaphore.
    Call before launching the work; rebinding is picked up by ``_ask`` at call time."""
    global _FANOUT, _LLM_SEM
    _FANOUT = max(1, int(n))
    _LLM_SEM = threading.Semaphore(_FANOUT)


def _per(e: dict) -> str:
    """`` (2023)`` period suffix for an evidence row, blank when the value is a scalar."""
    p = (e.get("period") or "").strip()
    return f" ({p})" if p else ""


def _grid_header_cols(line: str) -> dict[str, int] | None:
    """For a dumped-grid header row (``| | A | B | … |`` — an empty top-left corner cell, then
    spreadsheet column letters), return ``{column-letter: index in the pipe-split}`` so a data row's
    cell for a given column can be read by the same index. Returns ``None`` for any other line
    (the ``---`` separator, ``**N**`` data rows, prose), distinguished by the empty-corner rule."""
    cells = line.split("|")
    if len(cells) < 3 or cells[1].strip() != "":      # a real grid header has an empty top-left corner
        return None
    cols = {c.strip(): i for i, c in enumerate(cells) if re.fullmatch(r"[A-Z]{1,3}", c.strip())}
    return cols or None


def _cell_on_page(celltok: str, text: str) -> bool:
    """Whether a bare cell ref (``E4``, ``AU4``) occurs on the page as a *whole* token.

    A plain substring check lets ``E4`` match ``E40``/``AE4`` and wave a hallucinated cell
    through — fatal for auditable provenance — so anchor the match on column/row boundaries.

    Two page shapes carry cells differently. The formula-model pages cite a cell inline as a
    literal token (``value [E20]``) — caught by the boundary-anchored search below. The dumped
    spreadsheet grids (``data_room`` ledgers) instead encode the coordinate *positionally*: a
    column-letter header row (``| | A | B | … | E |``) and a row-number label (``| **20** | …``),
    so ``E20`` is never written out. For those we verify the cell at the **intersection** of that
    column and that labelled row is actually present and non-empty — checking column-present AND
    row-present *independently* (the old guard) let a page that merely had column E somewhere and
    row 20 somewhere validate an empty/absent E20, i.e. a hallucinated cite.
    """
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(celltok)}(?![0-9])", text):
        return True
    m = re.fullmatch(r"([A-Za-z]{1,3})(\d{1,7})", celltok)
    if not m:
        return False
    col, row = m.group(1).upper(), m.group(2)
    # Scan top-down: each grid header governs the data rows beneath it (a page can hold several
    # grids). Accept on the first labelled `**row**` line whose cell under `col` is non-empty.
    row_re = re.compile(rf"^\|\s*\*\*{re.escape(row)}\*\*\s*\|")
    header_cols: dict[str, int] | None = None
    for line in text.splitlines():
        cols = _grid_header_cols(line)
        if cols is not None:
            header_cols = cols
        elif header_cols and col in header_cols and row_re.match(line):
            cells = line.split("|")
            idx = header_cols[col]
            if idx < len(cells) and cells[idx].strip():
                return True
    return False


def parse_action(raw: str) -> dict | None:
    """Extract the single JSON object from a model turn (tolerates code fences/prose)."""
    s = raw.strip()
    if "```" in s:
        parts = s.split("```")
        s = max(parts, key=len).lstrip("json").strip() if len(parts) >= 3 else s.strip("`")
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(s[start : end + 1])
    except (ValueError, json.JSONDecodeError):
        return None


def salvage_array(raw: str, key: str) -> list:
    """Recover the COMPLETE objects from a ``"<key>": [ {…}, {…}, … ]`` array in possibly-truncated
    output. The retriever's full-row extraction over a dense grid can overflow ``max_tokens`` and
    cut the JSON mid-object — ``parse_action`` then yields nothing and the page's evidence is lost
    entirely. This scans the array brace-aware (string/escape-safe) and returns every object that
    closed before the cutoff, so a truncated round still contributes the rows it did finish."""
    m = re.search(rf'"{re.escape(key)}"\s*:\s*\[', raw)
    if not m:
        return []
    objs: list = []
    depth, obj_start, in_str, esc = 0, None, False, False
    for j in range(m.end(), len(raw)):
        c = raw[j]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                obj_start = j
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    objs.append(json.loads(raw[obj_start : j + 1]))
                except (ValueError, json.JSONDecodeError):
                    pass
                obj_start = None
        elif c == "]" and depth == 0:
            break
    return objs


def _ask(system: str, user: str, max_tokens: int, timeout: float | None = None,
         label: str = "") -> tuple[dict | None, str]:
    """One-shot LLM call: system + user → (parsed JSON action, raw text).

    Acquires ``_LLM_SEM`` so concurrent branches/pages never exceed the request cap — vLLM
    continuous-batches whatever does land at once, which is where the speed-up comes from.
    ``timeout`` is per-call: a big-``max_tokens`` extraction (full-row + narrative) can run long
    on a loaded vLLM, so its caller raises this above the shared default to avoid a socket timeout
    truncating the round. ``None`` → ``config.agent_persona_timeout("default", 120)``. ``label``
    names the persona for the parse-failure log — a silent ``parse_action`` miss (→ empty action
    → wasted round) was previously invisible.
    """
    if timeout is None:
        timeout = config.agent_persona_timeout("default", 120.0)
    with _LLM_SEM:
        raw = chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max_tokens,
            timeout=timeout,
        )
    act = parse_action(raw)
    if act is None:
        # A cut-off object (no closing brace) is the usual cause — flag it so a too-tight
        # max_tokens budget is diagnosable rather than silently degrading to empty evidence.
        truncated = bool(raw) and not raw.rstrip().endswith("}")
        log.warning("parse_action miss: persona=%s max_tokens=%d truncated=%s rawlen=%d",
                    label or "?", max_tokens, truncated, len(raw or ""))
        if _debug():
            log.warning("  raw tail: %s", (raw or "")[-200:])
    elif _debug():
        log.info("ask ok: persona=%s max_tokens=%d rawlen=%d", label, max_tokens, len(raw or ""))
    return act, raw


def _rec(sub: int, seq: int, agent: str, action: str, arg: str, thought: str) -> dict:
    """One trace record. ``sub``/``seq`` are the branch index and intra-branch order; the
    global ``step`` is reassigned in ``core`` after the parallel branches merge."""
    return {"step": seq, "sub": sub, "agent": agent, "action": action, "arg": arg, "thought": thought}
