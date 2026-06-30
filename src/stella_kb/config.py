"""Central configuration: ``config.yaml`` + environment overrides.

Precedence per value: **environment variable > config.yaml > built-in default**. Every legacy
``STELLA_*``/``MNA_*``/``RAGAS_*`` env var still overrides its config key, so scripts and
per-run overrides keep working unchanged. Secrets (``DART_MCP_TOKEN``, ``DART_API_KEY``) are
**not** here — read those from ``os.environ`` / ``.env`` directly.

Imported from anywhere in the repo:
    from src.stella_kb.config import llm_url, llm_model        # apps/agent, eval/
    from ..config import parse_concurrency                     # within src/stella_kb/*
Loads ``configs/config.yaml`` (legacy: repo-root ``config.yaml``; override with ``STELLA_CONFIG``). PyYAML + stdlib
only, so it imports cleanly in the lean ``.venv-ragas`` too.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import yaml

from . import ROOT, WORKBOOK

def _resolve_config_path() -> Path:
    """``STELLA_CONFIG`` env wins; else ``configs/config.yaml`` (current layout), falling back to
    the legacy repo-root ``config.yaml`` so either layout / a fresh checkout still loads."""
    env = os.environ.get("STELLA_CONFIG")
    if env:
        return Path(env)
    primary = ROOT / "configs" / "config.yaml"
    return primary if primary.exists() else ROOT / "config.yaml"


_CONFIG_PATH = _resolve_config_path()


@lru_cache(maxsize=1)
def _data() -> dict:
    if _CONFIG_PATH.exists():
        return yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return {}


def get(*path: str, env: str | None = None, default: Any = None,
        cast: Callable[[Any], Any] | None = None) -> Any:
    """Resolve one value: env var (if set) > config.yaml at ``path`` > ``default``.

    ``path`` is the nested-key path, e.g. ``get("llm", "url")``. ``cast`` (e.g. ``int``) is
    applied to whatever wins — important since env vars arrive as strings.
    """
    val: Any = None
    if env is not None and os.environ.get(env) is not None:
        val = os.environ[env]
    if val is None:
        node: Any = _data()
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        val = node
    if val is None:
        val = default
    if val is None or cast is None:
        return val
    return cast(val)


# --- typed accessors: one place per setting (env name · yaml path · fallback default) -------

def llm_url() -> str:
    return get("llm", "url", env="STELLA_LLM_URL", default="http://123.37.5.219:8001/v1")


def llm_model() -> str:
    return get("llm", "model", env="STELLA_LLM_MODEL", default="gemma-4-31B-it")


def llm_temperature() -> float:
    """Sampling temperature for every chat call (default 0.0 — the build/agent want determinism;
    vLLM is still non-deterministic at 0 due to continuous batching). A query-affecting A/B knob."""
    return get("llm", "temperature", env="STELLA_LLM_TEMPERATURE", default=0.0, cast=float)


def llm_max_tokens() -> int:
    """Default output-token cap for a chat call when the caller doesn't pass its own. Per-call
    overrides (the agent personas set their own) still win; this is just the client fallback."""
    return get("llm", "max_tokens", env="STELLA_LLM_MAXTOK", default=512, cast=int)


def llm_timeout() -> float:
    """Default per-request socket timeout (seconds) for a chat call, when the caller passes none."""
    return get("llm", "timeout", env="STELLA_LLM_TIMEOUT", default=60.0, cast=float)


def tool_llm_url() -> str:
    return get("llm", "tool", "url", env="STELLA_TOOL_LLM_URL", default=llm_url())


def tool_llm_model() -> str:
    return get("llm", "tool", "model", env="STELLA_TOOL_LLM_MODEL", default=llm_model())


def parse_concurrency() -> int:
    return get("concurrency", "parse", env="STELLA_CONCURRENCY", default=6, cast=int)


def agent_fanout() -> int:
    return get("concurrency", "fanout", env="STELLA_FANOUT", default=4, cast=int)


def agent_router_top_k() -> int:
    """Max pages the router opens for ONE sub-question in a single round. Opening several related
    pages at once (reads fan out in parallel) is cheaper than picking one and paying for a serial
    ``gap``→retry round, so this is the recall/latency knob. yaml ``agent.router_top_k`` (5)."""
    return get("agent", "router_top_k", env="MNA_ROUTER_TOPK", default=5, cast=int)


def agent_max_steps() -> int:
    """Per-branch read budget: the initial page read + up to (max_steps-1) ``gap``→retry rounds.
    The single source for both the direct ``run`` path and the supervisor's wiki worker (so they
    no longer drift). Callers may still pass an explicit value (API ``max_steps`` query param)."""
    return get("agent", "max_steps", env="MNA_MAX_STEPS", default=3, cast=int)


def agent_recursion_limit() -> int:
    """LangGraph ``recursion_limit`` for an agent run: planner → solve fan-out → auditor is ~3
    supersteps, so the default 25 is generous headroom — raise only if a deep graph trips it."""
    return get("agent", "recursion_limit", env="MNA_RECURSION_LIMIT", default=25, cast=int)


def agent_cross_ref_pair_cap() -> int:
    """Max PDF↔Excel cross-ref partner pages auto-attached to one sub-question (over-retrieval
    guard for :func:`agent_cross_ref_pairing`)."""
    return get("agent", "cross_ref_pair_cap", env="MNA_CROSSREF_CAP", default=3, cast=int)


def agent_persona_tokens(persona: str, default: int) -> int:
    """Per-persona LLM output-token budget (``agent.tokens.<persona>``: planner/router/retriever/
    verifier/synthesizer). Too tight a budget truncates the JSON object → empty parse → wasted
    retry round, so this is the quality/cost knob the per-call logging surfaces. ``default`` is the
    code fallback when the key is absent. Env ``MNA_TOKENS_<PERSONA>`` overrides one persona."""
    return get("agent", "tokens", persona,
               env=f"MNA_TOKENS_{persona.upper()}", default=default, cast=int)


def agent_persona_timeout(kind: str, default: float) -> float:
    """Per-call request timeout in seconds (``agent.timeouts.<kind>``). A big-``max_tokens``
    extraction (retriever) runs long on a loaded vLLM, so it sets a higher value than the shared
    ``default``. Env ``MNA_TIMEOUT_<KIND>`` overrides one kind."""
    return get("agent", "timeouts", kind,
               env=f"MNA_TIMEOUT_{kind.upper()}", default=default, cast=float)


def agent_cross_ref_pairing() -> bool:
    """When true, the router auto-attaches a routed page's PDF↔Excel cross-ref partner(s)
    (``derives_from``/``cited_by``) so a cross-check/reconcile question opens both the FDD report
    page and its Excel source. Capped to avoid over-retrieval. Default **off** — query-affecting,
    so enable for the A/B (env ``MNA_CROSSREF_PAIR``) before turning it on by default."""
    return get("agent", "cross_ref_pairing", env="MNA_CROSSREF_PAIR",
               default=False, cast=lambda v: str(v).lower() in ("1", "true", "yes", "on"))


def agent_deterministic_retrieve() -> bool:
    """When true, the retriever first tries a **deterministic** parse of a page's ``value [cell]``
    table (``retrieval.tools.extract_page_items``) and, on a hit, skips that page's LLM extraction — a
    latency win for already-structured pages. Pages with no parseable table fall back to the LLM.
    Default **off** — it changes evidence selection, so enable only after a clean quality A/B."""
    return get("agent", "deterministic_retrieve", env="MNA_DET_RETRIEVE",
               default=False, cast=lambda v: str(v).lower() in ("1", "true", "yes", "on"))


def agent_skip_verifier() -> bool:
    """When true, the per-branch verifier LLM call is skipped (verdict forced ``ok`` → no retry).

    Ablation lever for the 'does the verifier earn its call + retry round?' question: in trace mode
    the verifier already auto-accepts, and otherwise it mostly decides whether to re-route. Default
    **off** (verifier on); flip via ``MNA_SKIP_VERIFY`` for the A/B before changing any default."""
    return get("agent", "skip_verifier", env="MNA_SKIP_VERIFY",
               default=False, cast=lambda v: str(v).lower() in ("1", "true", "yes", "on"))


def eval_fanout(default: int = 8) -> int:
    return get("concurrency", "eval_fanout", env="STELLA_EVAL_FANOUT", default=default, cast=int)


def ragas_concurrency() -> int:
    return get("concurrency", "ragas", env="RAGAS_CONCURRENCY", default=6, cast=int)


def pdf_describe_concurrency() -> int:
    return get("concurrency", "pdf_describe", env="MNA_PDF_DESCRIBE_CONCURRENCY",
               default=4, cast=int)


def pdf_file_concurrency() -> int:
    """How many PDFs the data-room ingest runs through the vision pipeline *concurrently*. The PDFs
    are independent during the data-room build (no cross-PDF formula DAG / index), so overlapping
    them keeps the shared vLLM batch full instead of draining one short PDF at a time. Total in-flight
    LLM calls ≈ this × ``pdf_describe`` (vision) or × the structure pool — the endpoint scales
    linearly well past that, so 4 is a safe default. yaml ``concurrency.pdf_files`` / env
    ``MNA_PDF_FILE_CONCURRENCY``."""
    return get("concurrency", "pdf_files", env="MNA_PDF_FILE_CONCURRENCY", default=4, cast=int)


def max_table_pages() -> int:
    return get("parsing", "max_table_pages", env="MNA_PARSE_MAX_TABLE_PAGES",
               default=80, cast=int)


def pdf_vision_cache() -> str:
    return get("cache", "pdf_vision", env="PDF_VISION_CACHE", default=".cache/pdf_vision")


def pdf_page_png_cache() -> str:
    return get("cache", "pdf_page_png", env="PDF_PAGE_PNG_CACHE", default=".cache/pages")


def pdf_structure_cache() -> str:
    """Disk cache for the PDF *structuring* LLM calls (structure_section / build_document), so a
    wiki rebuild is deterministic and doesn't perturb eval results."""
    return get("cache", "pdf_structure", env="PDF_STRUCTURE_CACHE", default=".cache/pdf_structure")


def convert_root() -> Path:
    """Corpus root whose files ``convert`` normalizes in place (legacy formats → ingestable ones).
    Defaults to the v0.3 data room; override per-run with ``MNA_CONVERT_ROOT`` / the positional arg."""
    return Path(get("convert", "root", env="MNA_CONVERT_ROOT", default="raw/v0.3/data"))


def pdf_page_cap() -> int:
    """Max PDF pages the data-room ingest visions per document (front-loaded; covers exec summaries
    and the substantive schedules). Default mirrors ``wiki.data_room.PDF_PAGE_CAP`` (=25); override
    with ``MNA_PDF_PAGE_CAP``. ≤0 means no cap (the caller treats that as "all pages")."""
    return get("wiki", "pdf_page_cap", env="MNA_PDF_PAGE_CAP", default=25, cast=int)


def curate_yaml() -> Path:
    """Curated **ingest manifest** policy for a document data room (the v0.3 build): an
    ``exclude:``/``include:`` glob list selecting which files of a nested corpus enter the wiki.
    Hand-authored + git-committed (like ``decks.yaml``/``routes.yaml``), so the curated subset is
    deterministic and auditable. Default ``knowledge/<version>/curate.yaml`` (version from the
    build's ``MNA_WIKI_DATA`` dir); explicit file via env ``MNA_WIKI_CURATE``; absent = built-in
    ``data_room.DEFAULT_EXCLUDE``."""
    return Path(get("wiki", "curate", env="MNA_WIKI_CURATE",
                    default=str(curation_dir() / _version_token(wiki_data_dir()) / "curate.yaml")))


def soffice_bin() -> str:
    """LibreOffice headless binary used by ``convert`` (``soffice``/``libreoffice`` on PATH, or an
    absolute path). It's the converter for every office format we normalize."""
    return get("convert", "soffice", env="MNA_SOFFICE_BIN", default="soffice")


def hwp5odt_bin() -> str:
    """pyhwp's ``hwp5odt`` binary — the first leg of HWP→ODT→PDF in ``convert``. Defaults to the
    name on PATH; ``convert`` also falls back to the one installed alongside the venv python."""
    return get("convert", "hwp5odt", env="MNA_HWP5ODT_BIN", default="hwp5odt")


def wiki_parse_cache() -> str:
    """Disk cache for the wiki *parse* LLM calls (``parse_llm``: a sheet's grid → structure).

    Content-addressed (the key is the model + full prompt, i.e. the grid), so it doubles as the
    **incremental** mechanism: an unchanged sheet hashes to the same key → cache hit → no LLM
    call, while an edited sheet misses and re-parses. Also makes a rebuild deterministic (the
    shared vLLM is non-deterministic even at temp 0). Clear the dir to force a fresh parse."""
    return get("cache", "wiki_parse", env="WIKI_PARSE_CACHE", default=".cache/wiki_parse")


def wiki_prose_cache() -> str:
    """Disk cache for the wiki *compile* prose LLM calls (the page's 'What this is' blurb).

    Same content-addressed/incremental rationale as :func:`wiki_parse_cache`: keyed on the
    facts handed to the model, so a page whose values are unchanged reuses its prose for free."""
    return get("cache", "wiki_prose", env="WIKI_PROSE_CACHE", default=".cache/wiki_prose")


def dart_mcp_url() -> str:
    return get("dart", "mcp_url", env="DART_MCP_URL", default="http://127.0.0.1:8003/sse")


# --- wiki build I/O paths (env-overridable; defaults preserve the canonical knowledge/ tree) -----
# The whole wiki pipeline (dump_md -> parse_llm -> compile -> index -> pdf_pages) reads its
# input workbook/PDFs and writes its md/parsed/wiki artifacts through these accessors, so a
# second corpus can be built into an isolated tree without touching the canonical build:
#     MNA_WIKI_WORKBOOK=<x.xlsx> MNA_WIKI_DATA=knowledge/v0.2 MNA_WIKI_PDF_DIR=raw/v0.2 \
#         python -m src.stella_kb.wiki.dump_md --all   (and the rest of the stages)
# Defaults reproduce the original hardcoded paths exactly, so existing runs/tests are unchanged.

def wiki_workbook() -> str:
    """Source workbook for the wiki Excel pipeline (dump_md/index)."""
    return get("wiki", "workbook", env="MNA_WIKI_WORKBOOK", default=WORKBOOK)


def alias_stopwords() -> list:
    """Extra structural alias terms to drop in the dedup pass, beyond the curated
    ``wiki.dedup.STRUCTURAL_STOPWORDS``. yaml: ``wiki.alias_stopwords`` (a list of terms)."""
    v = get("wiki", "alias_stopwords", default=[])
    return list(v) if isinstance(v, (list, tuple)) else []


def cross_ref_llm_judge() -> bool:
    """When true, the PDF→Excel cross-ref build (``wiki.cross_refs``) uses the cached, whitelist-
    guarded LLM judge to confirm ambiguous Tier-B candidates. Default **off** — deterministic
    fund-identity + specific-metric links only, pending a quality check on the judged edges."""
    return get("wiki", "cross_ref_llm_judge", env="MNA_CROSSREF_JUDGE",
               default=False, cast=lambda v: str(v).lower() in ("1", "true", "yes", "on"))


def wiki_data_dir() -> Path:
    """Base dir holding the wiki build artifacts (``md/`` ``parsed/`` ``wiki/``). Default is the
    canonical build under ``knowledge/v0.1`` (each corpus version lives in its own ``knowledge/<v>``)."""
    return Path(get("wiki", "data_dir", env="MNA_WIKI_DATA", default="knowledge/v0.1"))


def wiki_pdf_dir() -> Path:
    """Dir scanned for FDD report PDFs to ingest. Default: ``<data_dir>/raw``."""
    return Path(get("wiki", "pdf_dir", env="MNA_WIKI_PDF_DIR",
                    default=str(wiki_data_dir() / "raw")))


def curation_dir() -> Path:
    """Repo-tracked root for hand-authored, **version-controlled** curation, laid out per dataset
    version: ``knowledge/<version>/{decks,routes}.yaml`` — co-located with each version's build. These
    two yamls stay committed via a ``.gitignore`` exception even though the rest of ``knowledge/`` is
    ignored (regenerable), so a fresh checkout still has the curation. Override the root with env
    ``MNA_CURATION_DIR`` / yaml ``curation.dir``."""
    return Path(get("curation", "dir", env="MNA_CURATION_DIR", default=str(ROOT / "knowledge")))


def _version_token(d: Path | str) -> str:
    """Dataset-version token from a knowledge/wiki dir, per the ``knowledge/<version>/wiki`` convention:
    ``knowledge/v0.2`` → ``v0.2`` and ``knowledge/v0.2/wiki`` → ``v0.2``. Names the ``knowledge/<version>/``
    subdir that pairs with the build/dataset."""
    p = Path(d)
    return p.parent.name if p.name == "wiki" else p.name


def wiki_decks_yaml() -> Path:
    """Curated **first-layer** deck index the PDF build reads to override the LLM-synthesized
    document node (per-deck ``title``/``description``). A hand-authored, git-committed input —
    precedence is curated > LLM > default — so the upper layer is deterministic and auditable
    (OpenKB curated-whitelist pattern). Default ``knowledge/<version>/decks.yaml`` (version from
    the build's ``MNA_WIKI_DATA`` dir); explicit file via env ``MNA_WIKI_DECKS``; absent = pure
    LLM."""
    return Path(get("wiki", "decks", env="MNA_WIKI_DECKS",
                    default=str(curation_dir() / _version_token(wiki_data_dir()) / "decks.yaml")))


def wiki_md_dir() -> Path:
    return wiki_data_dir() / "md"


def wiki_parsed_dir() -> Path:
    return wiki_data_dir() / "parsed"


def wiki_pages_dir() -> Path:
    return wiki_data_dir() / "wiki" / "pages"


def wiki_index_json() -> Path:
    return wiki_data_dir() / "wiki" / "index.json"


def wiki_index_md() -> Path:
    return wiki_data_dir() / "wiki" / "INDEX.md"


def agent_wiki_dir() -> Path:
    """Wiki the query agent reads (index.json / pages / ledgers). Default ``knowledge/wiki`` (the
    canonical valuation-model wiki); point it at another build (e.g. ``knowledge/v0.2/wiki``) to
    serve or evaluate against a different corpus without touching the agent code."""
    return Path(get("agent", "wiki_dir", env="MNA_AGENT_WIKI", default="knowledge/v0.1/wiki"))


def agent_routes_yaml(wiki_dir: str | Path | None = None) -> Path:
    """Curated routing table for the query agent — ``term → page(s)`` so a hit skips the router
    LLM. Resolved **per dataset**: ``knowledge/<version>/routes.yaml`` (version from the served
    ``wiki_dir``, default the process wiki). Committed alongside ``decks.yaml``. An explicit env
    ``MNA_AGENT_ROUTES`` file overrides for single-dataset serving (don't set it when serving
    several datasets — it would force one table for all). Absent = pure-LLM routing."""
    base = Path(wiki_dir) if wiki_dir else agent_wiki_dir()
    return Path(get("agent", "routes", env="MNA_AGENT_ROUTES",
                    default=str(curation_dir() / _version_token(base) / "routes.yaml")))


if __name__ == "__main__":  # smoke: print the resolved config
    print(f"config file: {_CONFIG_PATH}  (exists={_CONFIG_PATH.exists()})")
    for name in ("llm_url", "llm_model", "tool_llm_url", "tool_llm_model", "parse_concurrency",
                 "agent_fanout", "eval_fanout", "ragas_concurrency", "pdf_describe_concurrency",
                 "pdf_file_concurrency", "max_table_pages", "pdf_vision_cache",
                 "pdf_page_png_cache", "dart_mcp_url"):
        print(f"  {name:24s} = {globals()[name]()!r}")
