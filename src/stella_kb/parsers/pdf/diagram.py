"""Diagram legend-coverage check + focused re-prompt — the enforcement half of structure-diagram
ingest.

The vision prompt (``describe.py``) asks the model to tag **every** box with its legend category
(``CP LLC (노란색)``, ``Celadon Core LLC ★ (흰색)``) and to emit a per-category 특수표시 박스 list.
On dense org charts (60+ boxes) the model reliably transcribes the *legend* but skips the per-box
binding — so a question like "which entities require bank settlement (★)?" is unanswerable even
though the legend names the category. Prompt text alone already failed (the Jun-22 rebuild still
dropped it), so this module *detects* the gap deterministically and triggers a second, narrow
vision call that asks only for the missing per-category box lists.

Deterministic parts (``parse_legend`` / ``covered_keys`` / ``missing_categories``) are pure string
work — tested offline. ``augment_diagram`` is the one vision-touching entry point (cached), and is
a no-op when there's no under-covered diagram, so it's safe to call on every page.
"""

from __future__ import annotations

import logging
import re

log = logging.getLogger("stella_kb.parsers.pdf.diagram")

_ARROW = r"(?:\$\\rightarrow\$|→|->|⟶|➔)"
# A legend entry: "- 노란색 박스 → ...", "- $\star$ 기호 → ...", "- 점선 테두리 → ...".
# key = a Korean colour word (…색), a line style (실선/점선), or the star symbol.
_LEGEND_LINE = re.compile(
    rf"^\s*[-*•]\s*(?P<key>\$\\star\$|★|[가-힣]+색|실선|점선)\s*"
    rf"(?:박스|기호|테두리|영역|선|표시)?\s*{_ARROW}\s*(?P<meaning>.*\S)?",
)
# the default / "everything else" category — gray boxes are usually left untagged by design, so a
# missing 회색 binding is not a real gap and must not trigger a re-prompt.
_DEFAULT_KEYS = {"회색", "회식", "灰色"}


def _norm_key(k: str) -> str:
    return "★" if k in ("$\\star$", "★") else k


def parse_legend(md: str) -> dict[str, str]:
    """``{legend_key: meaning}`` for every legend entry across the page's diagram block(s)."""
    out: dict[str, str] = {}
    for line in md.splitlines():
        m = _LEGEND_LINE.match(line)
        if m:
            out[_norm_key(m.group("key"))] = (m.group("meaning") or "").strip()
    return out


def _legend_line_set(md: str) -> set[int]:
    return {i for i, line in enumerate(md.splitlines()) if _LEGEND_LINE.match(line)}


def _grouped_has_members(key: str, line: str) -> bool:
    """A 특수표시-style grouping line ``- 흰색(To Be Set-up): New Fund III GP`` with real members
    (not ``없음``/empty) — the format the augmentation re-prompt emits."""
    m = re.match(rf"^\s*[-*•]\s*{re.escape(key)}\s*(?:\([^)]*\))?\s*[:：]\s*(?P<members>.*)$", line)
    return bool(m) and m.group("members").strip() not in ("", "없음", "-", "—", "N/A")


def covered_keys(md: str) -> set[str]:
    """Legend keys that actually bind to a **box** somewhere outside the legend itself.

    Covered when the key is used as an inline box tag (``CP LLC (노란색)``, ``(녹색=Cayman)``), or
    heads a 특수표시 grouping line with real members (``- 흰색(To Be Set-up): New Fund III GP``),
    or — for the star — ``$\\star$``/``★`` shows up in the box/connection lists. Legend lines are
    excluded so a key isn't counted "covered" by its own definition.
    """
    legend = _legend_line_set(md)
    body_lines = [line for i, line in enumerate(md.splitlines()) if i not in legend]
    body = "\n".join(body_lines)
    covered: set[str] = set()
    for key in parse_legend(md):
        if key == "★":
            if "$\\star$" in body or "★" in body:
                covered.add(key)
            continue
        inline = re.search(rf"\(\s*{re.escape(key)}", body)  # CP LLC (노란색) / (녹색=…)
        grouped = any(_grouped_has_members(key, line) for line in body_lines)
        if inline or grouped:
            covered.add(key)
    return covered


def missing_categories(md: str, ignore: set[str] | None = None) -> list[str]:
    """Non-default legend categories declared but with **no** tagged box in the body — the gap.

    Gray (the conventional default) is ignored: its boxes are normally untagged, so its absence is
    expected, not a transcription failure.
    """
    ignore = (ignore or set()) | _DEFAULT_KEYS
    legend = parse_legend(md)
    if not legend:
        return []
    return [k for k in legend if k not in ignore and k not in covered_keys(md)]


def has_diagram(md: str) -> bool:
    return "[다이어그램]" in md or bool(parse_legend(md))


# A box/connection list header inside a [다이어그램] block: "**박스 목록**", "**연결 목록**",
# "**Apex**". The names listed under these are the diagram's entities — the routable terms a
# structure question asks about ("who owns X", "which SPC holds Y"). They live in `- …` list
# lines (not pipe tables), so the table-term harvester misses them entirely.
_BOX_HEADER = re.compile(r"\*\*\s*(?:박스\s*목록|연결\s*목록|Apex)\s*\*\*", re.I)
_APEX_LINE = re.compile(r"\*\*\s*Apex\s*\*\*\s*[:：]\s*(?P<name>.+\S)")
_BULLET = re.compile(r"^\s*[-*•]\s+(?P<body>.+\S)\s*$")
# trailing box annotation to strip from a name: "(녹색=PEF)", "(노란색)", ": 100.0%", "[FDD3]".
_BOX_ANNOT = re.compile(r"\s*\([^)]*\)\s*$|\s*[:：]\s*\S.*$|\s*\[[^\]]*\]\s*$")
_BOX_NUMERIC = re.compile(r"^[\d\s.,%xX()\-+]+$")


def _clean_box_name(s: str) -> str:
    """Strip a box/connection entry down to its bare entity name — drop the colour/category
    annotation, the edge percentage, and any ``[tag]``/emphasis."""
    s = re.sub(r"[*_`]+", "", s).strip()
    prev = None
    while prev != s:  # peel repeated trailing annotations ("CP LLC (노란색) : 100.0%")
        prev = s
        s = _BOX_ANNOT.sub("", s).strip()
    return s.strip(" |·-\t")


def diagram_terms(md: str, cap: int = 80) -> list[str]:
    """Entity names from a page's ``[다이어그램]`` block(s) — the Apex plus every box/connection
    list member — as routable alias terms. Returns ``[]`` when the page has no diagram.

    Names are read only from ``**박스 목록**``/``**연결 목록**``/``**Apex**`` sections (legend and
    note lines are skipped), the colour/percentage annotation is stripped, and connection lines
    (``A → B : 100%``) contribute *both* endpoints. Order-preserving + deduped (normalized)."""
    if not has_diagram(md):
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        name = _clean_box_name(name)
        if not (2 <= len(name) <= 60) or _BOX_NUMERIC.match(name):
            return
        k = _norm_key(name).replace(" ", "").casefold()
        if k and k not in seen:
            seen.add(k)
            out.append(name)

    in_list = False
    for line in md.splitlines():
        apex = _APEX_LINE.search(line)
        if apex:
            _add(apex.group("name"))
            in_list = False
            continue
        if _BOX_HEADER.search(line):
            in_list = True
            continue
        stripped = line.strip()
        # a heading / horizontal rule / other bold marker (범례, …) ends the box-list scope, so
        # bullets in a later section (notes, Links) never leak in as entities.
        if stripped.startswith(("#", "---", "===", "**")):
            in_list = False
            continue
        if not in_list:
            continue
        m = _BULLET.match(line)
        if not m:
            continue
        body = m.group("body")
        # a connection line carries an arrow; both endpoints are entities
        for part in re.split(_ARROW, body) if re.search(_ARROW, body) else [body]:
            _add(part)
            if len(out) >= cap:
                return out
    return out


_REPROMPT_SYS = (
    "당신은 한국 금융 자료의 구조도(조직도·지배구조도)를 정밀하게 읽는 도우미입니다. "
    "이미지를 보고 요청한 분류별 박스 목록만 정확히 작성하세요. 박스 이름은 이미지에 적힌 그대로, "
    "지어내지 마세요."
)


def build_reprompt(missing: list[str], legend: dict[str, str]) -> str:
    """The focused user prompt for the second vision pass — only the missing per-category lists."""
    cats = "\n".join(f"- {k}: {legend.get(k, '')}".rstrip() for k in missing)
    return (
        "이 페이지의 구조도에서 범례가 정의한 아래 분류 각각에 대해, 그 색/기호/테두리로 강조된 "
        "**모든 박스 이름**을 이미지에서 빠짐없이 찾아 나열하세요. 기본색(회색) 박스는 제외합니다.\n\n"
        f"대상 분류:\n{cats}\n\n"
        "정확히 이 형식의 markdown만 출력하세요(분류에 해당하는 박스가 없으면 '없음'):\n"
        "**특수표시 박스 (보강)**\n"
        "- <분류>(<의미>): <박스1>, <박스2>, …\n"
    )


def merge_augmentation(md: str, augment_block: str) -> str:
    """Append the re-prompt's 특수표시 박스 block into the page, right after the diagram body.

    Inserted before the first footnote/horizontal-rule that trails a diagram (``---``/``Note[``)
    so it stays inside the diagram region; otherwise appended at the end.
    """
    block = augment_block.strip()
    if not block:
        return md
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "---" or line.strip().startswith("Note["):
            return "\n".join(lines[:i] + ["", block, ""] + lines[i:])
    return md.rstrip() + "\n\n" + block + "\n"


def augment_diagram(md: str, image_path: str, model: str) -> str:
    """If the page has an under-covered diagram legend, run a focused second vision pass to recover
    the per-category box lists and merge them in. No-op (returns ``md`` unchanged) when there's no
    gap, and best-effort: a vision failure is logged and the original ``md`` is kept.
    """
    if not has_diagram(md):
        return md
    missing = missing_categories(md)
    if not missing:
        return md
    legend = parse_legend(md)
    prompt = build_reprompt(missing, legend)
    log.info("diagram augment: legend categories without tagged boxes -> %s (re-prompting)", missing)
    from . import vision

    _AUGMENT_MAX_TOKENS = 2000

    def _compute() -> str:
        return vision.invoke_vision(system=_REPROMPT_SYS, prompt=prompt,
                                    image_path=image_path, model=model, max_tokens=_AUGMENT_MAX_TOKENS)

    try:
        # cached on (model, system, user, max_tokens) like the main describe call — distinct prompt
        # AND budget → distinct key, so the augmentation re-prompt is also free on a rebuild.
        augment = vision.get_or_compute(model=model, system=_REPROMPT_SYS, user=prompt + f"\n[img:{image_path}]",
                                        compute=_compute, max_tokens=_AUGMENT_MAX_TOKENS)
    except RuntimeError as e:  # vision flake → keep the original page, just log the residual
        log.warning("diagram augment failed (%s) — keeping original; categories still missing: %s",
                    e, missing)
        return md
    merged = merge_augmentation(md, augment)
    still = missing_categories(merged)
    if still:
        log.warning("diagram augment incomplete: categories still untagged after re-prompt: %s", still)
    return merged
