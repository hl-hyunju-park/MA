"""Hierarchical drill-down navigator — the agent **reads the wiki nav files** to pick pages.

For a document-data-room wiki (v0.3+) the flat ``INDEX.md`` is too big to hand a router, so the
build emits a navigable tree (``wiki/nav_tree.py``): ``router.yaml`` (navigate AMONG the top folders)
and one ``index.md`` per folder (navigate WITHIN, to its subfolders). This walks that tree the way a
person browses the data room — **opening the actual files at each hop**:

  1. read ``router.yaml``      → LLM picks which top folder(s) hold the answer
  2. read that folder's ``index.md`` → LLM picks a subfolder
  3. repeat until a chosen folder's subtree is small enough → take its pages

So a hand-edit to ``router.yaml`` / an ``index.md`` steers the agent: the markdown is the source of
truth it reads. The ``index['nav']`` JSON is used only to *resolve* a picked folder label to its
path + pages (robust) and to know subtree sizes for the early-stop — never as the text the LLM sees.

Used by ``solve._route`` on the first attempt when ``index['nav']`` exists; on a miss the caller
falls back to the flat-index router + alias lookup, so nothing regresses for v0.1/v0.2.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.stella_kb import config

from ...retrieval import lookup_pages
from . import engine
from .engine import load_prompt

NAVIGATE = load_prompt("navigate")

_MAX_DEPTH = 4          # data room is ≤5 levels deep; cap the LLM hops per sub-question
_PICK_PER_LEVEL = 2     # folders the LLM may pick at each level (recall vs. fan-out)


def _subtree_pages(num: str, folders: dict) -> list[str]:
    """Every page under a folder (its own + all descendants'), order-stable."""
    out = list(folders[num]["pages"])
    for c in folders[num]["children"]:
        out.extend(_subtree_pages(c, folders))
    return out


def _fallback_doc(labels_descs: list[tuple[str, int, str]]) -> str:
    """Reconstruct a folder-listing when the actual file can't be read (missing wiki_dir / file) —
    so navigation still works offline. Mirrors the relevant lines of router.yaml / index.md."""
    return "\n".join(f"- {label} ({n}건): {desc or '(요약 없음)'}" for label, n, desc in labels_descs)


def _read_doc(path: Path | None, candidates: list[str], folders: dict) -> str:
    """The text the LLM reads for one hop: the actual nav file if present, else a rebuilt listing."""
    if path is not None:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            pass
    return _fallback_doc([(folders[c]["label"], folders[c]["n_pages"], folders[c].get("desc", ""))
                          for c in candidates])


def _pick(ask: str, doc: str, candidates: list[str], folders: dict, where: str) -> list[str]:
    """One LLM step: from ``doc`` (a router.yaml / index.md the agent just read), choose ≤
    ``_PICK_PER_LEVEL`` of ``candidates`` (folder numbers) by their label."""
    by_norm = {re.sub(r"\s+", "", folders[c]["label"]).casefold(): c for c in candidates}
    user = (f"질문: {ask}\n\n[{where}]\n{doc}\n\n"
            f"위 내용에서 답이 있을 폴더를 최대 {_PICK_PER_LEVEL}개 고르세요. Return the folders JSON.")
    act, _ = engine._ask(NAVIGATE, user, config.agent_persona_tokens("router", 400), label="navigate")
    picked: list[str] = []
    for raw in (act or {}).get("folders") or []:
        key = re.sub(r"\s+", "", str(raw)).casefold()
        num = by_norm.get(key) or next((v for k, v in by_norm.items() if key and (key in k or k in key)), None)
        if num and num not in picked:
            picked.append(num)
    return picked[:_PICK_PER_LEVEL]


def navigate(ask: str, index: dict, hints: list[str] | None = None,
             page_cap: int = 8, wiki_dir: str | None = None) -> list[str]:
    """Drill the nav tree for one sub-question → candidate page keys, **reading router.yaml then the
    chosen folders' index.md** from ``wiki_dir`` at each hop. Returns ``[]`` when there's no nav tree
    or the walk finds nothing (caller falls back). Drilling stops early down a branch once a chosen
    folder's whole subtree fits ``page_cap``; the alias ``lookup`` over ``hints`` ranks the final set
    so the on-topic pages survive the cap."""
    nav = index.get("nav")
    if not nav:
        return []
    folders = nav["folders"]
    wd = Path(wiki_dir) if wiki_dir else None

    # hop 1 — read router.yaml, pick among the top folders
    roots = nav["roots"]
    router_doc = _read_doc(wd / "router.yaml" if wd else None, roots, folders)
    frontier = _pick(ask, router_doc, roots, folders, "router.yaml")
    if not frontier:
        return []

    pages: list[str] = []
    for _ in range(_MAX_DEPTH):
        nxt: list[str] = []
        for num in frontier:
            f = folders[num]
            if f["n_pages"] <= page_cap or not f["children"]:
                pages.extend(_subtree_pages(num, folders))      # small/leaf → take all, stop
                continue
            # hop 2+ — read THIS folder's index.md, pick a subfolder
            md = (wd / f["md"]) if (wd and f.get("md")) else None
            doc = _read_doc(md, f["children"], folders)
            pages.extend(f["pages"])                             # direct pages are candidates too
            nxt.extend(_pick(ask, doc, f["children"], folders, f["label"] + "/index.md"))
        if not nxt:
            break
        frontier = nxt

    pages = list(dict.fromkeys(pages))         # dedup, keep order
    if len(pages) > page_cap and hints:        # rank within candidates by alias lookup
        rank = lookup_pages(index, hints)
        cand = set(pages)
        pages = [p for p in rank if p in cand] + [p for p in pages if p not in set(rank)]
    return pages[:page_cap]
