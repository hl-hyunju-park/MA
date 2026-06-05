"""Wiki I/O — deterministic access to the built wiki (``data/wiki/``). No LLM here."""

from .tools import (
    INDEX_JSON,
    INDEX_MD,
    PAGES_DIR,
    WIKI_DIR,
    load_index,
    lookup,
    open_page,
)

__all__ = [
    "WIKI_DIR", "INDEX_MD", "INDEX_JSON", "PAGES_DIR",
    "load_index", "lookup", "open_page",
]
