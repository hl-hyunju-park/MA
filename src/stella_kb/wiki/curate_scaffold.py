"""Auto-scaffold ``decks.yaml`` + ``routes.yaml`` from a built wiki ``index.json``.

The two curation files used to be hand-authored against a first build (mine the real page keys,
write YAML, validate, rebuild). This module automates that for the **document-data-room** build
(v0.3+): it reads the freshly-built index and emits both files deterministically, so a rebuild
keeps them in sync with the corpus instead of drifting. Wired into ``scripts/run_ingest_v03.sh``
as the ``[scaffold]`` stage (after the build, before lint).

Design — the generated tables must be SAFE to use live (the agent routes on them unreviewed):

* **routes.yaml** maps a hint term → ONE page, and only for terms that are safe by construction:
  an alias whose normalized key resolves to exactly one page (unique), is "clean" (no leading
  enumerator like ``10.``/``가.``/``①``, not a bare year/number, not a generic word), and doesn't
  collide with another term after normalization. This deliberately EXCLUDES time-series metrics:
  ``지급여력비율`` isn't a single alias (its per-row forms ``10. 지급여력비율`` are, and those are
  filtered out as enumerated), and any term living on many monthly pages fails the unique test —
  so the agent never gets routed to one arbitrary quarter. A miss just falls back to the LLM router.
* **decks.yaml** emits one block per PDF document: the LLM document-node ``title`` plus a ``pages``
  pin freezing the lead (``FDD1``) page name — which is usually a routes.yaml target — so a later
  rebuild's LLM titler can't rename it out from under its route. Descriptions are left to the LLM
  (omitted here) so they regenerate fresh rather than freezing possibly-worse text.

Both files are OVERWRITTEN each build (the chosen mode): fully hands-off, always in sync. To pin a
hand-curated value instead, stop running this stage for that dataset (or edit the heuristic).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Generic identity nouns that must never become a standalone route key (they collide across many
# pages / read as boilerplate). A clean unique alias equal to one of these is dropped.
_STOP = {
    "현황", "명세서", "내역", "보고서", "승인", "승인에", "공문", "신청", "자료", "목록", "리스트",
    "증명서", "평가", "계산서", "스케쥴", "스케줄", "상세", "요약", "개요", "총괄", "합계",
    "소계", "기준", "구분", "비고", "참고", "기타", "원본", "페이지", "표", "그림", "차트",
    "이익", "손실", "자산", "부채", "자본", "수익", "비용", "금액", "비율", "잔액", "단위",
    "values", "value", "total", "sheet", "table", "page", "summary", "overview", "notes",
    # generic / function / admin words that read as plausible queries but point nowhere specific
    "회사", "사업", "업무", "영위", "영위가능", "본사", "변경", "통보", "사실", "따른", "체결",
    "안내", "전문", "신고용", "가입", "매뉴얼", "홈페이지", "사모", "외화", "결과", "이력", "권한",
    "소유", "문서", "변환", "표지", "목차", "주석", "별도", "연결", "지급", "설정", "제한",
}
# A leading list enumerator (1. / 12) / 가. / Ⅱ. / ① …) marks a row label, not a routable concept.
_ENUM = re.compile(r"^\s*(?:\d{1,3}|[가-힣]|[Ⅰ-ⅻIVXivx]{1,4}|[①-⑳]|[a-zA-Z])\s*[.)\]]")
# A bare year / quarter / date token ("2024", "FY2023", "26.1Q", "202503") — never a concept.
_DATEY = re.compile(r"^\s*(?:FY)?\s*\d{2,4}(?:[.\-]\d{1,2})?(?:[.\-]\d{1,2})?\s*(?:년|월|말|분기|[Qq]\d?|\d?[Qq])?\s*$")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).casefold()


def _is_clean_term(term: str) -> bool:
    """Whether ``term`` is a distinctive concept safe to use as a route key (vs. a row label,
    enumerator, date, or generic noun)."""
    t = (term or "").strip()
    if not (2 <= len(t) <= 40):
        return False
    if _ENUM.match(t) or _DATEY.match(t):
        return False
    if _norm(t) in {_norm(s) for s in _STOP}:
        return False
    # must carry at least one Hangul or ASCII letter (drop pure-symbol/number tokens)
    if not re.search(r"[가-힣A-Za-z]", t):
        return False
    # a short pure-ASCII token is an acronym (KDB/KB/NH/SDC) — too generic/ambiguous to route on
    if not re.search(r"[가-힣]", t) and len(t) < 4:
        return False
    # drop tokens dominated by digits (e.g. "2023(복구)") — likely a period-stamped label
    letters = sum(c.isalpha() or "가" <= c <= "힣" for c in t)
    digits = sum(c.isdigit() for c in t)
    return letters >= digits


# A subsection bigger than this is a time-series ledger (e.g. 128 monthly pages), not a structural
# unit — routing its name would open a flood of period pages, so only small subsections are routed.
_MAX_FANOUT = 4


def _leaf(section_prefix: str) -> str:
    """Strip the dotted DD numbering from a section/folder label: ``2.1.2. K-ICS BS`` → ``K-ICS BS``."""
    return re.sub(r"^\s*[\d]+(?:\.[\d]+)*\.?\s*", "", section_prefix).strip()


def _tokens(text: str) -> list[str]:
    """Split a folder/file label into candidate identity tokens (drops separators + conjunctions)."""
    parts = re.split(r"[_/·,&()]|\s+|및|와|과|등", text)
    return [p.strip() for p in parts if p.strip()]


def scaffold_routes(index: dict) -> dict[str, list[str]]:
    """``{term: [page, ...]}`` from STRUCTURAL identity — subsection names + PDF document tokens —
    never raw cell contents (those are unique-but-meaningless, e.g. a department footnote).

    * Spreadsheet **subsections** (the page-key prefix, e.g. ``2.1.2. K-ICS BS``) with ≤
      ``_MAX_FANOUT`` pages route their leaf term to those page(s); bigger subsections are
      time-series ledgers and are skipped.
    * PDF **documents** route each distinctive token of their ``doc`` token to the lead page, but
      only tokens UNIQUE across all docs (``회계정책서`` spans 19 docs → dropped; ``금융상품`` →
      kept). A term used by two different sources is dropped entirely (ambiguous → unsafe).
    """
    pages = index.get("pages", {})
    documents = index.get("documents", {})

    routes: dict[str, list[str]] = {}
    norm_count: dict[str, int] = {}      # normalized key -> #distinct terms claiming it

    def add(term: str, targets: list[str]) -> None:
        if not _is_clean_term(term) or not targets:
            return
        key = re.sub(r"\s+", " ", term).strip()
        norm_count[_norm(key)] = norm_count.get(_norm(key), 0) + 1
        routes.setdefault(key, sorted(targets))

    # 1) spreadsheet subsections → their (small) page set
    sub: dict[str, list[str]] = {}
    for k, p in pages.items():
        if p.get("source") == "XLSX":
            sub.setdefault(k.split("__")[0], []).append(k)
    for prefix, pgs in sub.items():
        if 1 <= len(pgs) <= _MAX_FANOUT:
            add(_leaf(prefix), pgs)

    # 2) PDF documents → lead (FDD1) page, keyed by tokens unique across all docs
    lead: dict[str, str] = {}
    for name, p in pages.items():
        if p.get("source") != "PDF":
            continue
        m = re.match(r"FDD1 — \[(?P<doc>.+?)\] ", name)
        if m:
            lead[m.group("doc")] = name
    tok_docs: dict[str, set[str]] = {}   # normalized token -> set of docs that contain it
    doc_tokens: dict[str, set[str]] = {}
    for doc in documents:
        folder, _, stem = doc.partition(" _ ")
        toks = {t for t in _tokens(_leaf(folder)) + _tokens(stem) if _is_clean_term(t)}
        doc_tokens[doc] = toks
        for t in toks:
            tok_docs.setdefault(_norm(t), set()).add(doc)
    for doc, toks in doc_tokens.items():
        if doc not in lead:
            continue
        # cap to the 3 longest (most distinctive) tokens unique to this doc — a descriptive
        # filename otherwise floods routes with address parts / filler (양덕동, 창원시, 제11층)
        unique = sorted((t for t in toks if len(tok_docs.get(_norm(t), ())) == 1),
                        key=lambda t: (-len(t), t))
        for t in unique[:3]:
            add(t, [lead[doc]])

    # drop any key claimed by 2+ distinct terms (collision after normalization → ambiguous)
    routes = {k: v for k, v in routes.items() if norm_count.get(_norm(k), 0) == 1}
    return dict(sorted(routes.items(), key=lambda kv: (kv[1][0], kv[0])))


def scaffold_decks(index: dict) -> dict[str, dict]:
    """``{doc: {title, pages: {1: <FDD1 name>}}}`` — one block per PDF document, pinning its lead
    page name (a frequent route target) so a rebuild can't rename it. Description left to the LLM."""
    documents = index.get("documents", {})
    pages = index.get("pages", {})
    # lead page (FDD1) name per doc, recovered from the page keys: "FDD1 — [<doc>] <label>"
    lead: dict[str, str] = {}
    for name, p in pages.items():
        if p.get("source") != "PDF":
            continue
        m = re.match(r"FDD(\d+) — \[(?P<doc>.+?)\] (?P<label>.+)$", name)
        if m and m.group(1) == "1":
            lead[m.group("doc")] = m.group("label")
    decks: dict[str, dict] = {}
    for doc in sorted(documents):
        block: dict = {}
        title = (documents[doc] or {}).get("title")
        if title:
            block["title"] = title
        if doc in lead:
            block["pages"] = {1: lead[doc]}
        if block:
            decks[doc] = block
    return decks


# ----------------------------------------------------------------- YAML rendering (with headers)
def _yaml_dump(obj) -> str:
    import yaml
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False,
                          width=10_000)


_ROUTES_HEADER = """\
# Curated routing table — AUTO-GENERATED by src/stella_kb/wiki/curate_scaffold.py.
#
# OVERWRITTEN on every build (scripts/run_ingest_v03.sh [scaffold] stage) — do not hand-edit; your
# changes are replaced. Read at QUERY time by apps/agent/retrieval/tools.py :: route_lookup: a
# sub-question whose hint_terms match a key opens the listed page directly and SKIPS the router LLM.
#
# Only terms that resolve to EXACTLY ONE page and are "clean" (no leading enumerator, not a bare
# year/number, not a generic noun) are emitted, so a route can't misfire to the wrong page. Keys
# are normalized (whitespace-insensitive, case-folded) on load. Time-series metrics (지급여력비율,
# K-ICS ratio, …) span many monthly pages → not unique → intentionally NOT routed (the LLM router
# + alias lookup handle them).
"""

_DECKS_HEADER = """\
# Curated first-layer document index — AUTO-GENERATED by src/stella_kb/wiki/curate_scaffold.py.
#
# OVERWRITTEN on every build (scripts/run_ingest_v03.sh [scaffold] stage) — do not hand-edit. Read
# at BUILD time by src/stella_kb/wiki/data_room.py :: ingest_pdfs (curated > LLM > default). KEYS =
# the per-PDF `doc` token. Each block pins the lead (FDD1) page name so a rebuild can't rename a
# routes.yaml target; the document description is left to the LLM (regenerated fresh each build).
"""


def _scalarize(routes: dict[str, list[str]]) -> dict[str, object]:
    """A single-page route reads cleaner as a scalar (``term: page``) than a 1-item list."""
    return {k: (v[0] if len(v) == 1 else v) for k, v in routes.items()}


def write_files(index: dict, decks_path: Path, routes_path: Path) -> tuple[int, int]:
    """Render + overwrite both curation files. Returns ``(n_routes, n_decks)``."""
    routes = scaffold_routes(index)
    decks = scaffold_decks(index)
    decks_path.parent.mkdir(parents=True, exist_ok=True)
    routes_body = _yaml_dump(_scalarize(routes)) if routes else "{}\n"
    routes_path.write_text(_ROUTES_HEADER + "\n" + routes_body, encoding="utf-8")
    decks_path.write_text(_DECKS_HEADER + "\n" + (_yaml_dump(decks) if decks else "{}\n"),
                          encoding="utf-8")
    return len(routes), len(decks)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Scaffold decks.yaml + routes.yaml from a built wiki.")
    ap.add_argument("wiki", nargs="?", help="built wiki dir (has index.json); "
                    "default: config wiki dir")
    ap.add_argument("--out", help="curation dir to write decks.yaml/routes.yaml "
                    "(default: the wiki dir's parent, e.g. knowledge/<version>)")
    ap.add_argument("--dry-run", action="store_true", help="print counts, don't write")
    args = ap.parse_args(argv)

    if args.wiki:
        wiki = Path(args.wiki)
    else:
        from ..config import agent_wiki_dir
        wiki = agent_wiki_dir()
    index_json = wiki / "index.json"
    if not index_json.exists():
        print(f"!! no index.json at {index_json} — build the wiki first", file=sys.stderr)
        return 1
    index = json.loads(index_json.read_text(encoding="utf-8"))
    out = Path(args.out) if args.out else wiki.parent

    routes = scaffold_routes(index)
    decks = scaffold_decks(index)
    print(f"scaffold: {len(routes)} route(s), {len(decks)} deck block(s) from {index_json}")
    if args.dry_run:
        for k, v in list(routes.items())[:20]:
            print(f"  route  {k!r} -> {v}")
        return 0
    n_r, n_d = write_files(index, out / "decks.yaml", out / "routes.yaml")
    print(f"  wrote {out/'routes.yaml'}  ({n_r} routes)")
    print(f"  wrote {out/'decks.yaml'}  ({n_d} decks)")
    return 0


if __name__ == "__main__":  # smoke: scaffold the configured wiki (dry-run if no index)
    raise SystemExit(main(sys.argv[1:]))
