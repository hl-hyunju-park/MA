"""Prompt templates kept out of code, one file per prompt.

System prompts for the three LLM uses live here as ``<name>.txt`` so they can be
edited and reviewed without touching Python. Load with ``load("wiki_prose_system")``.
The path resolves relative to this package, so it works regardless of cwd.
"""

from pathlib import Path

_DIR = Path(__file__).resolve().parent


def load(name: str) -> str:
    """Return the text of prompt ``<name>.txt`` from this folder."""
    return (_DIR / f"{name}.txt").read_text(encoding="utf-8").strip()
