"""Hierarchical navigation index for a document-data-room wiki (v0.3+).

A flat ``INDEX.md`` is ~370KB / ~190k tokens at 2,000+ pages — too big to hand a planner. This
builds a **tree of folder summaries** mirroring the data-room directory structure so the agent can
*drill down* (``router.yaml`` → folder ``index.md`` → subfolder → pages) instead of reading the
whole catalogue at once — the PageIndex / OpenKB "tree reasoning" pattern.

What it produces (run as a build stage, after assemble):

* ``index.json["nav"]`` — the machine-readable tree the agent navigates: ``{roots, folders}`` where
  each folder carries ``{num, name, label, desc, children, pages, n_pages}``. ``desc`` is an
  LLM one-liner ("what this folder contains"), content-addressed cached like the rest of the build.
* ``router.yaml`` — the top level: each root folder (``1. 회사일반현황`` …) → its summary + the
  list of its immediate subfolders. The agent's entry point.
* ``nav/<…nested…>/index.md`` — one per folder, at its REAL nested path (mirrors the data room):
  its summary, relative links to its subfolders' index.md, and links to the data files below.
* ``nav/<…nested…>/<page>.md`` — the **actual data content** (the input grid / vision page) placed
  directly in its folder, so the tree bottoms out in the real files, not just summaries. Content is
  copied from ``wiki/pages/<key>.md`` (which the agent still reads); the nav copy is browsable.

The named hierarchy comes from the **source directory** (``raw/v0.3/data``) — only it carries
every intermediate folder's name (``2.6. 투자자산`` is a pure container, named nowhere in the page
keys). Each built page is mapped to its leaf folder by the dotted number its key carries
(``2.6.3.5.1. …`` → folder ``2.6.3.5.1``). Folders with no built pages in their subtree are pruned.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..llm import cached_chat
from ..prompts import load as load_prompt

_SYSTEM = load_prompt("nav_folder_system")
_PAGE_SYSTEM = load_prompt("nav_page_system")
_NAV_CACHE = ".cache/nav_summary"        # content-addressed folder-summary cache (cached_chat)
_PAGE_CACHE = ".cache/nav_page_summary"  # content-addressed per-page one-liner cache (cached_chat)
_PAGES_PER_PROMPT = 40                    # cap leaf page titles fed to a summary (prompt budget)
_PAGE_CONTENT_MAX = 2400                  # cap page-md chars fed to a per-page summary (token budget)


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _num_of(label: str) -> str:
    """Leading dotted number of a folder/section label: ``2.6. 투자자산`` → ``2.6`` (``""`` if none)."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)", label)
    return m.group(1) if m else ""


def _name_of(label: str) -> str:
    """Folder label minus its dotted number: ``2.6. 투자자산`` → ``투자자산``."""
    return re.sub(r"^\s*\d+(?:\.\d+)*\.?\s*", "", label).strip()


def _parent(num: str) -> str:
    """Parent folder number: ``2.6.3`` → ``2.6``; a root (``2``) → ``""``."""
    return num.rsplit(".", 1)[0] if "." in num else ""


def _page_folder_num(key: str, source: str) -> str:
    """The leaf folder number a built page belongs to, recovered from its key."""
    if source == "PDF":
        m = re.match(r"FDD\d+ — \[(.+?)(?: _ |\])", key)
        prefix = m.group(1) if m else key
    else:
        prefix = key.split("__")[0]
    return _num_of(prefix)


def page_breadcrumb(key: str, source: str, nav: dict) -> list[str]:
    """A page's full location as a breadcrumb of **nav folder labels** down to the file/sheet —
    e.g. ``2.9. 특수관계자__주석_2023.12__별도`` → ``['2. 재무', '2.9. 특수관계자', '주석_2023.12',
    '별도']``. Walks the nav tree for the ancestor folders, then appends the within-folder
    file/sheet (XLSX) or page label (PDF). Falls back to the raw ``__``-split if the page isn't
    placed in the tree."""
    folders = (nav or {}).get("folders", {})
    # The key shape is authoritative for PDF (``FDD<n> — [...]``) vs grid (``…__…`` segments), so
    # trust it over the ``source`` hint — which may be a default when the page isn't in the index.
    is_pdf = source == "PDF" or bool(re.match(r"FDD\d+ — \[", key))
    num = _page_folder_num(key, "PDF" if is_pdf else "XLSX")
    while num and num not in folders:           # an unknown number → nearest known ancestor
        num = _parent(num)
    labels = [folders[a]["label"] for a in _ancestor_chain(num) if a in folders] if num else []
    if is_pdf:
        m = re.match(r"FDD\d+ — \[.+?\] (.+)", key)
        tail = [m.group(1)] if m else []
    else:
        tail = key.split("__")[1:]              # file, sheet under the leaf folder
    crumb = labels + tail
    return crumb or [s for s in key.split("__") if s]


# --------------------------------------------------------------------------- tree from source dirs
def build_folder_tree(root: Path) -> dict[str, dict]:
    """``{num: {num, name, label, children: [num], parent}}`` for every numbered folder under
    ``root`` (names NFC-normalized). Unnumbered dirs are skipped — the DD corpus numbers them all."""
    folders: dict[str, dict] = {}
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        label = _nfc(d.name)
        num = _num_of(label)
        if not num:
            continue
        folders[num] = {"num": num, "name": _name_of(label), "label": label,
                        "children": [], "parent": _parent(num)}
    # link children (sort by numeric tuple so 2.10 sorts after 2.2)
    for num, f in folders.items():
        p = f["parent"]
        if p and p in folders:
            folders[p]["children"].append(num)
    for f in folders.values():
        f["children"].sort(key=lambda n: [int(x) for x in n.split(".")])
    return folders


def assign_pages(folders: dict[str, dict], index: dict) -> None:
    """Attach each page to its leaf folder (``pages``) and roll subtree totals up to ``n_pages``.

    A page whose number isn't a known folder is hung on its nearest existing ancestor, so nothing
    is dropped if the source tree and the build drift slightly."""
    for f in folders.values():
        f.setdefault("pages", [])
    for key, p in index.get("pages", {}).items():
        num = _page_folder_num(key, p.get("source", ""))
        while num and num not in folders:        # walk up to the nearest known ancestor
            num = _parent(num)
        if num:
            folders[num]["pages"].append(key)
    for f in folders.values():
        f["pages"].sort()
    # subtree page totals, deepest first
    for num in sorted(folders, key=lambda n: -n.count(".")):
        f = folders[num]
        f["n_pages"] = len(f["pages"]) + sum(folders[c]["n_pages"] for c in f["children"])


def prune_empty(folders: dict[str, dict]) -> dict[str, dict]:
    """Drop folders with no built pages anywhere in their subtree (excluded/boilerplate dirs)."""
    kept = {n: f for n, f in folders.items() if f["n_pages"] > 0}
    for f in kept.values():
        f["children"] = [c for c in f["children"] if c in kept]
    return kept


# ------------------------------------------------------------------------------- LLM summaries
def _summary_input(folder: dict, folders: dict, pages: dict) -> str:
    """The user message for one folder's summary: subfolder names+summaries, or leaf page titles."""
    lines = [f"폴더명: {folder['label']}"]
    if folder["children"]:
        lines.append("하위 폴더:")
        for c in folder["children"]:
            cf = folders[c]
            lines.append(f"- {cf['label']}: {cf.get('desc', '') or '(요약 없음)'}")
    titles = [pages[k].get("title") or pages[k].get("sheet") or k for k in folder["pages"]]
    if titles:
        lines.append("자료 제목:")
        lines += [f"- {t}" for t in titles[:_PAGES_PER_PROMPT]]
        if len(titles) > _PAGES_PER_PROMPT:
            lines.append(f"- … 외 {len(titles) - _PAGES_PER_PROMPT}건")
    return "\n".join(lines)


def summarize(folders: dict[str, dict], index: dict, *, concurrency: int = 4) -> None:
    """Fill each folder's ``desc`` with a cached LLM one-liner, bottom-up (a parent summary sees its
    children's). Deterministic + content-addressed: an unchanged folder is a cache hit, no LLM call."""
    pages = index.get("pages", {})
    by_depth: dict[int, list[str]] = {}
    for num in folders:
        by_depth.setdefault(num.count("."), []).append(num)

    def one(num: str) -> tuple[str, str]:
        user = _summary_input(folders[num], folders, pages)
        try:
            desc = cached_chat([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
                               cache_dir=_NAV_CACHE, temperature=0.0, max_tokens=200, timeout=60).strip()
        except Exception as e:  # noqa: BLE001 — a summary failure must not sink the build
            desc = ""
            print(f"  !! nav summary failed for {num}: {e}")
        return num, re.sub(r"\s+", " ", desc)

    for depth in sorted(by_depth, reverse=True):     # leaves first so parents can cite children
        nums = by_depth[depth]
        with ThreadPoolExecutor(max_workers=min(concurrency, len(nums))) as ex:
            for num, desc in ex.map(one, nums):
                folders[num]["desc"] = desc


def _page_summary_input(key: str, p: dict, src_pages: Path) -> str:
    """The user message for one page's one-liner: its location/title + the real grid/page content
    (the built ``pages/<key>.md``, capped), falling back to its item labels if the file is absent."""
    breadcrumb = p.get("desc") or p.get("section") or ""
    lines = [f"위치/제목: {breadcrumb}", f"제목: {p.get('title') or key}"]
    if p.get("n_items"):
        lines.append(f"항목 수: {p['n_items']}")
    body = src_pages / f"{key}.md"
    if body.exists():
        text = body.read_text(encoding="utf-8")[:_PAGE_CONTENT_MAX]
        lines += ["내용:", text]
    else:
        labels = [_clean_label(it.get("label") or "") for it in p.get("items") or []]
        labels = [l for l in labels if l][:30]
        if labels:
            lines += ["항목 레이블:", ", ".join(labels)]
    return "\n".join(lines)


def summarize_pages(index: dict, wiki_dir: Path, *, concurrency: int = 8) -> None:
    """Fill each page's ``nav_desc`` with a cached LLM one-liner describing its actual content (read
    from ``pages/<key>.md``). Mirrors :func:`summarize`: deterministic + content-addressed, so an
    unchanged page is a cache hit (no LLM call). A failure leaves ``nav_desc`` unset — :func:`_page_desc`
    then falls back to the item-composed line, so the build never sinks on a summary error."""
    pages = index.get("pages", {})
    src_pages = wiki_dir / "pages"
    keys = list(pages)

    def one(key: str) -> tuple[str, str]:
        user = _page_summary_input(key, pages[key], src_pages)
        try:
            desc = cached_chat([{"role": "system", "content": _PAGE_SYSTEM}, {"role": "user", "content": user}],
                               cache_dir=_PAGE_CACHE, temperature=0.0, max_tokens=160, timeout=60).strip()
        except Exception as e:  # noqa: BLE001 — a summary failure must not sink the build
            desc = ""
            print(f"  !! nav page summary failed for {key}: {e}")
        return key, re.sub(r"\s+", " ", desc)

    with ThreadPoolExecutor(max_workers=min(concurrency, max(1, len(keys)))) as ex:
        for key, desc in ex.map(one, keys):
            if desc:
                pages[key]["nav_desc"] = desc


# --------------------------------------------------------------------------------- assemble + render
def to_nav(folders: dict[str, dict]) -> dict:
    """The structured tree persisted to ``index['nav']`` and walked by the agent navigator. Each
    folder carries ``md`` — the relative path to its rendered index.md — so the agent can OPEN that
    file at navigation time (the markdown is the source of truth it reads, not just this JSON)."""
    roots = sorted((n for n, f in folders.items() if not f["parent"]),
                   key=lambda n: [int(x) for x in n.split(".")])
    keep = ("num", "name", "label", "desc", "children", "pages", "n_pages")
    out = {}
    for n, f in folders.items():
        node = {k: f.get(k, "") for k in keep}
        node["md"] = _rel_md(n, folders)
        out[n] = node
    return {"roots": roots, "folders": out}


def _rel_md(num: str, folders: dict) -> str:
    """A folder's index.md path relative to the wiki dir: ``nav/2. 재무/2.6. 투자자산/index.md``."""
    return "nav/" + "/".join(_safe(folders[a]["label"]) for a in _ancestor_chain(num)) + "/index.md"


def _index_summary(md_text: str) -> str:
    """The summary paragraph from a folder's index.md (the first non-heading line under the title)."""
    for ln in md_text.splitlines()[1:]:
        s = ln.strip()
        if s and not s.startswith("#"):
            return s.strip("_").strip()        # drop the "_(요약 없음)_" placeholder markers
    return ""


def render_router_yaml(nav: dict, wiki_dir: Path) -> str:
    """router.yaml = navigate AMONG the top folders. Each root entry is built by **reading that
    folder's index.md** (its summary) and carries an ``index:`` reference to it — so router.yaml is
    a consistent, derived top-level view of the index.md files, not an independently-generated one.
    Falls back to the in-memory desc if the index.md hasn't been written yet."""
    import yaml
    folders = nav["folders"]
    body = {}
    for num in nav["roots"]:
        f = folders[num]
        rel = _rel_md(num, folders)
        md = wiki_dir / rel
        desc = _index_summary(md.read_text(encoding="utf-8")) if md.exists() else f.get("desc", "")
        body[f["label"]] = {"desc": desc, "n_pages": f["n_pages"], "index": rel}
    header = ("# Hierarchical navigation — TOP LEVEL (AUTO-GENERATED by wiki/nav_tree.py).\n"
              "# router.yaml = navigate AMONG the data room's top folders (pick which one holds the\n"
              "# answer). Each entry's `desc` is read from that folder's index.md and `index:` points\n"
              "# to it — open that index.md to navigate WITHIN the folder (descend the nested tree).\n"
              "# Built bottom-up: leaf index.md first → parents → router.yaml references them last.\n\n")
    return header + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=10_000)


def _safe(label: str) -> str:
    """Folder label → a filesystem-safe path segment (only ``/`` is illegal in a name)."""
    return re.sub(r"/", "_", label)


def _page_basename(key: str, folder_label: str) -> str:
    """A short, folder-local filename stem for a data page: drop the folder-number prefix the key
    carries (``2.6.3.5.1. KTB… 1호__다올…_기준가격대장`` → ``다올…_기준가격대장``; a PDF page
    ``FDD1 — [doc] 표지`` → ``FDD1 — 표지``)."""
    if key.startswith(folder_label + "__"):
        name = key[len(folder_label) + 2:]
    else:
        m = re.match(r"(FDD\d+) — \[.+?\] (.+)", key)
        name = f"{m.group(1)} — {m.group(2)}" if m else key
    return _safe(name)


def _clean_label(s: str) -> str:
    """Normalize an item label for display: collapse whitespace runs, and fold *justification*
    spacing (a label that is all single characters — ``구 분`` → ``구분``) while keeping the spaces in
    genuine multi-word labels (``선급법인세 명세서`` stays as-is)."""
    s = re.sub(r"\s+", " ", s or "").strip()
    toks = s.split(" ")
    return "".join(toks) if len(toks) > 1 and all(len(t) == 1 for t in toks) else s


def _page_desc(p: dict) -> str:
    """The one-liner shown next to a data page in its folder index.md. Prefers the LLM summary
    (``nav_desc``, written by :func:`summarize_pages` — a real content description). Falls back, when
    that's absent (offline / ``--no-summaries`` build, or a failed summary), to a deterministic line
    composed from the grid's own item labels (``선급법인세 명세서: 사업영역·구분·적요·금액 (20개 항목)``),
    and finally to the templated ``desc``/``title``."""
    if p.get("nav_desc"):
        return p["nav_desc"]
    labels, seen = [], set()
    for it in p.get("items") or []:
        lab = _clean_label(it.get("label") or "")
        if lab and lab not in seen:
            seen.add(lab)
            labels.append(lab)
    if not labels:
        return p.get("desc") or p.get("title", "")
    lead, rest = labels[0], labels[1:]
    head = "·".join(rest[:4])
    n = p.get("n_items") or len(p.get("items") or [])
    tail = f" ({n}개 항목)" if n else ""
    return f"{lead}: {head}{tail}" if head else f"{lead}{tail}"


def _folder_page_files(folder: dict) -> list[tuple[str, str]]:
    """``[(page_key, md_filename)]`` for a folder's direct data pages — filenames unique within it
    (so the links in index.md and the files on disk always agree)."""
    used: set = set()
    out: list = []
    for k in folder["pages"]:
        base = _page_basename(k, folder["label"]) or "data"
        fn, i = f"{base}.md", 2
        while fn.casefold() in used:
            fn, i = f"{base} ({i}).md", i + 1
        used.add(fn.casefold())
        out.append((k, fn))
    return out


def render_folder_index(num: str, nav: dict, pages: dict) -> str:
    """One folder's ``index.md``: its summary, **relative links down to each subfolder's index.md**,
    and links to the **data files placed directly in this folder** (the actual input content)."""
    f = nav["folders"][num]
    out = [f"# {f['label']}", "", f.get("desc", "") or "_(요약 없음)_", ""]
    if f["children"]:
        out.append("## 하위 폴더")
        for c in f["children"]:
            cf = nav["folders"][c]
            link = f"<{_safe(cf['label'])}/index.md>"   # angle brackets → spaces allowed in md link
            out.append(f"- [{cf['label']}]({link}) ({cf['n_pages']}p) — {cf.get('desc','')}")
        out.append("")
    if f["pages"]:
        out.append("## 자료 (직속)")
        for k, fn in _folder_page_files(f):
            out.append(f"- [{fn[:-3]}](<{fn}>) — {_page_desc(pages.get(k, {}))}")
        out.append("")
    return "\n".join(out)


def _ancestor_chain(num: str) -> list[str]:
    """Folder numbers from the root down to ``num`` inclusive: ``2.6.3`` → ``[2, 2.6, 2.6.3]``."""
    chain, n = [], num
    while n:
        chain.append(n)
        n = _parent(n)
    return list(reversed(chain))


def write_render(nav: dict, index: dict, wiki_dir: Path) -> None:
    """Write the nested nav/ tree + router.yaml **bottom-up**: each folder's index.md sits at its
    real path (nav/2. 재무/2.6. 투자자산/…/index.md) mirroring the data room. Leaf index.md are
    written first, then their parents (so a parent is written after the children it links to), and
    router.yaml LAST — it reads each top folder's index.md for its summary + reference. The nav/ dir
    is rebuilt from scratch to avoid stale dirs."""
    import shutil

    wiki_dir.mkdir(parents=True, exist_ok=True)
    nav_dir = wiki_dir / "nav"
    if nav_dir.exists():
        shutil.rmtree(nav_dir)                       # clear stale (e.g. an old flat layout)
    folders = nav["folders"]
    pages = index.get("pages", {})
    src_pages = wiki_dir / "pages"            # the built per-page content (data_room writes here)
    # deepest folders first (most dotted-number components) → bottom-up file creation
    for num in sorted(folders, key=lambda n: -n.count(".")):
        f = folders[num]
        d = nav_dir.joinpath(*[_safe(folders[a]["label"]) for a in _ancestor_chain(num)])
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.md").write_text(render_folder_index(num, nav, pages), encoding="utf-8")
        # place each direct page's actual content as a specific .md IN this folder (the input data)
        for k, fn in _folder_page_files(f):
            body = src_pages / f"{k}.md"
            content = body.read_text(encoding="utf-8") if body.exists() else \
                f"# {pages.get(k, {}).get('title', k)}\n\n_(내용 파일 없음: {k})_\n"
            (d / fn).write_text(content, encoding="utf-8")
    # router.yaml references the now-written top index.md files (correct, consistent references)
    (wiki_dir / "router.yaml").write_text(render_router_yaml(nav, wiki_dir), encoding="utf-8")


def build(root: Path, wiki_dir: Path, *, summaries: bool = True) -> dict:
    """End-to-end: source dirs → tree → page assignment → prune → (LLM) summaries → persist + render.

    Writes ``index['nav']`` back into ``wiki_dir/index.json`` and renders router.yaml + nav/. Returns
    the nav dict."""
    index_path = wiki_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    folders = build_folder_tree(root)
    assign_pages(folders, index)
    folders = prune_empty(folders)
    if summaries:
        summarize_pages(index, wiki_dir)     # per-page one-liners (nav_desc), shown next to each file in index.md
        summarize(folders, index)
    nav = to_nav(folders)
    index["nav"] = nav
    index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    write_render(nav, index, wiki_dir)
    return nav


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Build the hierarchical nav tree for a data-room wiki.")
    ap.add_argument("root", help="source data-room dir (e.g. raw/v0.3/data)")
    ap.add_argument("--wiki", help="built wiki dir (has index.json); default: config wiki dir")
    ap.add_argument("--no-summaries", action="store_true", help="skip the LLM folder summaries (offline)")
    args = ap.parse_args(argv)
    if args.wiki:
        wiki = Path(args.wiki)
    else:
        from ..config import agent_wiki_dir
        wiki = agent_wiki_dir()
    if not (wiki / "index.json").exists():
        print(f"!! no index.json at {wiki} — build the wiki first", file=sys.stderr)
        return 1
    nav = build(Path(args.root), wiki, summaries=not args.no_summaries)
    print(f"nav: {len(nav['folders'])} folder(s), {len(nav['roots'])} root(s) -> {wiki}/router.yaml + nav/")
    for r in nav["roots"]:
        f = nav["folders"][r]
        print(f"  {f['label']}  ({f['n_pages']}p, {len(f['children'])} subfolder(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
