"""Dataset (wiki version) registry + per-request store.

A *dataset* is one built wiki under a directory (``index.json`` + ``pages/`` + ``ledgers/``).
The HTTP API selects one per request by a short **id** (``"default"``, ``"v0.2"``, …) rather
than a filesystem path — the id is resolved here against a config-driven registry
(``config.yaml`` ``agent.datasets``), so a client can never point the agent at an arbitrary
directory. Each dataset's index + INDEX.md are cached so concurrent requests reuse them.

Per-request retrieval stays concurrency-safe because the chosen wiki dir is threaded through
the agent state (``AgentState.wiki_dir`` → ``open_page``/``query_ledger``), never set as a
process-global — so two in-flight requests can target different datasets at once.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.stella_kb.config import agent_wiki_dir, get

DEFAULT = "default"


def registry() -> dict[str, str]:
    """``{id: wiki_dir}`` from ``config.yaml`` ``agent.datasets``, always incl. ``default``
    (which falls back to ``agent_wiki_dir()`` / ``MNA_AGENT_WIKI`` when not listed)."""
    reg = {str(k): str(v) for k, v in (get("agent", "datasets", default={}) or {}).items()}
    reg.setdefault(DEFAULT, str(agent_wiki_dir()))
    return reg


def available() -> list[str]:
    """Sorted dataset ids a client may pass as ``dataset``."""
    return sorted(registry())


def resolve_dir(dataset: str | None) -> Path:
    """Map a dataset id to its wiki dir. ``None``/empty → the default. Raises ``KeyError``
    (with the unknown id) if it isn't registered — the API turns that into a 422."""
    reg = registry()
    key = dataset or DEFAULT
    if key not in reg:
        raise KeyError(key)
    return Path(reg[key])


@lru_cache(maxsize=8)
def _load_index(path: str, _mtime: float) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=8)
def _load_md(path: str, _mtime: float) -> str:
    return Path(path).read_text(encoding="utf-8")


# Above this size the full per-page INDEX.md is too large to hand a planner/router prompt:
# a ~2,000-page data-room ToC is ~370KB (~190k tokens) and overflows the model context → the
# endpoint rejects the request (HTTP 400). Past the threshold we fall back to the heading-only
# section outline; the precise page candidates still reach the router via the alias ``lookup``.
# Small corpora (v0.1/v0.2 ≈ 17KB) stay under it and are handed the full ToC, byte-for-byte
# unchanged — so this only kicks in for the large document-data-room datasets (v0.3+).
INDEX_MD_MAX_CHARS = 60_000


def compact_outline(md: str) -> str:
    """INDEX.md compacted to fit a planner/router prompt. Returns ``md`` unchanged when it is
    already small enough (the common case); otherwise keeps every ``#``-prefixed line — the
    section/sub-section hierarchy — and drops the per-page bullets, which a huge ToC can't fit.
    The router still gets exact page candidates from the alias ``lookup``, so dropping the
    bullets costs the planner only breadth, not the ability to resolve a page."""
    if len(md) <= INDEX_MD_MAX_CHARS:
        return md
    return "\n".join(ln for ln in md.splitlines() if ln.lstrip().startswith("#"))


class WikiStore:
    """A resolved dataset: its wiki dir plus lazily-loaded, cached ``index`` and ``index_md``.

    Caching is keyed by (path, mtime) so a rebuilt wiki is picked up without a restart."""

    def __init__(self, dataset: str | None = None):
        self.dataset = dataset or DEFAULT
        self.wiki_dir = resolve_dir(dataset)
        self.index_json = self.wiki_dir / "index.json"
        self.index_md_path = self.wiki_dir / "INDEX.md"

    def exists(self) -> bool:
        return self.index_json.exists()

    @property
    def index(self) -> dict:
        return _load_index(str(self.index_json), self.index_json.stat().st_mtime)

    @property
    def index_md(self) -> str:
        return _load_md(str(self.index_md_path), self.index_md_path.stat().st_mtime)

    @property
    def index_outline(self) -> str:
        """The ToC handed to the planner/router — full INDEX.md for small datasets, the
        heading-only outline once it grows past :data:`INDEX_MD_MAX_CHARS` (see
        :func:`compact_outline`). Use this, not ``index_md``, for prompt seeding."""
        return compact_outline(self.index_md)


@lru_cache(maxsize=8)
def get_store(dataset: str | None = None) -> WikiStore:
    """Cached :class:`WikiStore` for a dataset id (raises ``KeyError`` for unknown ids)."""
    return WikiStore(dataset)
