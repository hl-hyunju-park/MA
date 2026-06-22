"""Agent prompt templates, kept out of code (one ``<name>.txt`` per prompt).

Mirrors ``src/stella_kb/prompts`` but scoped to the query agent, so the agent package is
self-contained. Load with ``load("planner")``; the path resolves relative to this folder, so
it works regardless of cwd.

**Composable prompts.** A prompt file may assemble itself from reusable *blocks* (kept under
``blocks/``) instead of being one monolith. Two line-directives are supported:

    {{include: blocks/synth_final_calc}}   # inline that file's text here (recursive, depth-capped)
    {{! free-form note for maintainers }}   # dropped before the prompt reaches the model

So a long persona prompt (e.g. the synthesizer, which accretes situational rules) becomes a thin
manifest of includes; adding a rule is a new ``blocks/<x>.txt`` + one include line, and each block
stays small and reviewable. Plain ``<name>.txt`` files with no directives load exactly as before.
"""

import re
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_INCLUDE = re.compile(r"^\{\{include:\s*(.+?)\s*\}\}$")
_COMMENT = re.compile(r"^\{\{!.*\}\}$")
_MAX_DEPTH = 10  # include-nesting guard (a cycle would otherwise recurse forever)


def _raw(name: str) -> str:
    """Read ``<name>.txt`` from this folder (``name`` may include a ``blocks/`` prefix)."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8")


def _expand(text: str, _depth: int = 0) -> str:
    """Resolve ``{{include: …}}`` (recursively) and drop ``{{! … }}`` comment lines."""
    if _depth > _MAX_DEPTH:
        raise RecursionError("prompt include nesting too deep (cycle?)")
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _COMMENT.match(stripped):
            continue  # maintainer note — never sent to the model
        m = _INCLUDE.match(stripped)
        if m:
            out.append(_expand(_raw(m.group(1)).strip(), _depth + 1))
        else:
            out.append(line)
    return "\n".join(out)


def load(name: str) -> str:
    """Return prompt ``<name>.txt``, with any ``{{include}}``/``{{!}}`` directives resolved."""
    return _expand(_raw(name)).strip()
