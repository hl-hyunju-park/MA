"""Deterministic offline tests for the hierarchical nav-tree builder (no LLM, no network).

Covers the structural pipeline — folder tree from source dirs, page→folder assignment by dotted
number, subtree page rollup, empty-folder pruning, and the router.yaml / index.md render. The LLM
``summarize`` step is not exercised here (it needs the vLLM); ``--no-summaries`` leaves ``desc`` empty.
"""

from __future__ import annotations

from src.stella_kb.wiki import nav_tree as nt


def test_page_breadcrumb_infers_pdf_from_key_shape():
    nav = {"folders": {"2": {"label": "2. 재무", "num": "2"},
                       "2.9": {"label": "2.9. 특수관계자", "num": "2.9"}},
           "roots": ["2"]}
    # grid page → folder labels + the '__'-split tail (file/sheet under the leaf folder)
    grid = nt.page_breadcrumb("2.9. 특수관계자__주석_2023.12__별도", "XLSX", nav)
    assert grid[-2:] == ["주석_2023.12", "별도"]

    # #6: a PDF-shaped key passed the WRONG source ("XLSX" — the evidence_sources default for a page
    # missing from the index) must STILL parse as PDF (the key shape is authoritative).
    pdf = nt.page_breadcrumb("FDD3 — [2.9. 특수관계자 _ 주석] 별도 거래 내역", "XLSX", nav)
    assert pdf[-1] == "별도 거래 내역"           # PDF page-label tail, not a garbled __-split


def test_num_name_parent_helpers():
    assert nt._num_of("2.6. 투자자산") == "2.6"
    assert nt._name_of("2.6. 투자자산") == "투자자산"
    assert nt._num_of("회사 (번호없음)") == ""
    assert nt._parent("2.6.3") == "2.6"
    assert nt._parent("2") == ""


def test_page_folder_num_xlsx_and_pdf():
    assert nt._page_folder_num("2.6.3.5.1. KTB캄보디아__대장", "XLSX") == "2.6.3.5.1"
    assert nt._page_folder_num("FDD1 — [2.8.3. 퇴직급여 _ 보고서] 목차", "PDF") == "2.8.3"
    assert nt._page_folder_num("FDD2 — [4. 세무 _ 증명서] 납세", "PDF") == "4"


def test_page_desc_prefers_llm_nav_desc():
    # the LLM one-liner (nav_desc) wins over the item-composed fallback when present
    p = {"nav_desc": "2023년 자산 계정의 선급법인세 명세", "title": "T",
         "n_items": 3, "items": [{"label": "선급법인세 명세서"}, {"label": "금 액"}]}
    assert nt._page_desc(p) == "2023년 자산 계정의 선급법인세 명세"


def test_page_desc_falls_back_to_items_then_title():
    # no nav_desc → deterministic item compose: lead label + distinct labels + count, NOT a name echo
    p = {"title": "계정별명세 - 자산 - 2023 · 선급법인세", "n_items": 20, "items": [
        {"label": "선급법인세 명세서"}, {"label": "사업영역"}, {"label": "구 분"},
        {"label": "적 요"}, {"label": "금 액"}, {"label": "비 고"}, {"label": "사업영역"}]}
    assert nt._page_desc(p) == "선급법인세 명세서: 사업영역·구분·적요·금액 (20개 항목)"  # 구 분→구분, dedup, head capped at 4
    # no items either → fall back to templated desc, then title
    assert nt._page_desc({"desc": "그리드 원문", "title": "T"}) == "그리드 원문"
    assert nt._page_desc({"title": "T"}) == "T"


def test_page_summary_input_uses_page_content(tmp_path):
    # the per-page summary prompt feeds the REAL grid content (pages/<key>.md), capped
    src = tmp_path / "pages"
    src.mkdir()
    (src / "k.md").write_text("# k\n\n| 지급여력비율 | 101.66 |", encoding="utf-8")
    msg = nt._page_summary_input("k", {"title": "경영실태평가", "n_items": 14}, src)
    assert "지급여력비율" in msg and "항목 수: 14" in msg
    # no content file → fall back to item labels in the prompt
    msg2 = nt._page_summary_input("missing", {"title": "T", "items": [{"label": "구 분"}]}, src)
    assert "구분" in msg2


# --- LLM summary stages (cached_chat mocked — no network) -------------------------------

def test_summarize_pages_fills_nav_desc_deterministically(tmp_path, monkeypatch):
    # stub cached_chat as a content-addressed echo so the stage is deterministic on rerun
    def fake(messages, **kw):
        user = messages[-1]["content"]
        return "요약: 법인세 그리드" if "법인세" in user else "요약: 기타"
    monkeypatch.setattr(nt, "cached_chat", fake)
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "k.md").write_text("# k\n\n법인세 명세", encoding="utf-8")
    index = {"pages": {"k": {"title": "법인세", "items": [{"label": "x"}]}}}

    nt.summarize_pages(index, tmp_path)
    assert index["pages"]["k"]["nav_desc"] == "요약: 법인세 그리드"
    nt.summarize_pages(index, tmp_path)                       # rerun → identical (deterministic)
    assert index["pages"]["k"]["nav_desc"] == "요약: 법인세 그리드"
    # and the LLM line now wins in the rendered entry (precedence end-to-end)
    assert nt._page_desc(index["pages"]["k"]) == "요약: 법인세 그리드"


def test_summarize_pages_graceful_when_llm_raises(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("vllm down")
    monkeypatch.setattr(nt, "cached_chat", boom)
    (tmp_path / "pages").mkdir()
    index = {"pages": {"k": {"title": "T", "n_items": 2,
                             "items": [{"label": "선급법인세 명세서"}, {"label": "금 액"}]}}}
    nt.summarize_pages(index, tmp_path)                       # must NOT raise
    assert "nav_desc" not in index["pages"]["k"]              # unset on failure
    assert nt._page_desc(index["pages"]["k"]).startswith("선급법인세 명세서")  # falls back to items


def test_summarize_folders_bottom_up_cites_children(tmp_path, monkeypatch):
    for d in ("2. 재무", "2. 재무/2.1. 재무제표"):
        (tmp_path / d).mkdir(parents=True)
    folders = nt.build_folder_tree(tmp_path)
    nt.assign_pages(folders, {"pages": {"2.1. 재무제표__bs": {"source": "XLSX", "title": "BS"}}})
    folders = nt.prune_empty(folders)
    captured = {}

    def fake(messages, **kw):
        user = messages[-1]["content"]
        label = user.splitlines()[0].replace("폴더명: ", "")
        captured[label] = user
        return f"요약({label})"
    monkeypatch.setattr(nt, "cached_chat", fake)

    nt.summarize(folders, {"pages": {"2.1. 재무제표__bs": {"title": "BS"}}})
    assert folders["2.1"]["desc"] == "요약(2.1. 재무제표)"
    assert folders["2"]["desc"] == "요약(2. 재무)"
    # the parent is summarized AFTER its child, so its prompt already cites the child's filled desc
    assert "요약(2.1. 재무제표)" in captured["2. 재무"]


def test_summarize_folders_graceful_when_llm_raises(tmp_path, monkeypatch):
    (tmp_path / "2. 재무").mkdir()
    folders = nt.build_folder_tree(tmp_path)
    idx = {"pages": {"2. 재무__x": {"source": "XLSX", "title": "X"}}}
    nt.assign_pages(folders, idx)
    folders = nt.prune_empty(folders)
    monkeypatch.setattr(nt, "cached_chat",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    nt.summarize(folders, idx)                               # must NOT raise
    assert folders["2"]["desc"] == ""                        # failed summary → empty, build survives


def test_clean_label_folds_only_justification_spacing():
    assert nt._clean_label("구 분") == "구분"           # all single chars → justification, fold
    assert nt._clean_label("선급법인세 명세서") == "선급법인세 명세서"   # multi-char words → keep space
    assert nt._clean_label("  a   b  ") == "ab"          # runs collapsed, then folded (single chars)


def _tree(tmp_path):
    for d in ("1. 회사", "1. 회사/1.1. 평가", "2. 재무", "2. 재무/2.6. 투자",
              "2. 재무/2.6. 투자/2.6.3. 수익증권"):
        (tmp_path / d).mkdir(parents=True)
    return nt.build_folder_tree(tmp_path)


def test_build_folder_tree_links_children(tmp_path):
    folders = _tree(tmp_path)
    assert set(folders) == {"1", "1.1", "2", "2.6", "2.6.3"}
    assert folders["2"]["children"] == ["2.6"]
    assert folders["2.6"]["children"] == ["2.6.3"]
    assert folders["1"]["name"] == "회사" and folders["2.6"]["parent"] == "2"


def test_assign_pages_and_rollup(tmp_path):
    folders = _tree(tmp_path)
    index = {"pages": {
        "1.1. 평가__x": {"source": "XLSX"},
        "2.6.3. 수익증권__y": {"source": "XLSX"},
        "FDD1 — [2.6. 투자 _ z] 표": {"source": "PDF"},      # sits directly in 2.6
    }}
    nt.assign_pages(folders, index)
    assert folders["1.1"]["pages"] == ["1.1. 평가__x"]
    assert folders["2.6.3"]["pages"] == ["2.6.3. 수익증권__y"]
    assert folders["2.6"]["pages"] == ["FDD1 — [2.6. 투자 _ z] 표"]
    assert folders["2"]["n_pages"] == 2          # 2.6 (1 direct) + 2.6.3 (1)
    assert folders["1"]["n_pages"] == 1


def test_assign_unknown_number_hangs_on_ancestor(tmp_path):
    folders = _tree(tmp_path)
    # 2.6.3.9 isn't a folder → page should attach to nearest known ancestor 2.6.3
    nt.assign_pages(folders, {"pages": {"2.6.3.9. 미지__p": {"source": "XLSX"}}})
    assert folders["2.6.3"]["pages"] == ["2.6.3.9. 미지__p"]


def test_prune_empty_drops_childless_pageless(tmp_path):
    for d in ("1. A", "1. A/1.1. B", "1. A/1.2. C"):
        (tmp_path / d).mkdir(parents=True)
    folders = nt.build_folder_tree(tmp_path)
    nt.assign_pages(folders, {"pages": {"1.1. B__x": {"source": "XLSX"}}})
    folders = nt.prune_empty(folders)
    assert "1.2" not in folders                    # empty subtree pruned
    assert folders["1"]["children"] == ["1.1"]     # and dropped from parent's child list


def test_to_nav_and_render(tmp_path):
    for d in ("2. 재무", "2. 재무/2.1. 재무제표"):
        (tmp_path / d).mkdir(parents=True)
    folders = nt.build_folder_tree(tmp_path)
    index = {"pages": {"2.1. 재무제표__bs": {"source": "XLSX", "title": "BS"}}}
    nt.assign_pages(folders, index)
    folders = nt.prune_empty(folders)
    folders["2"]["desc"], folders["2.1"]["desc"] = "재무 자료", "재무제표 BS/PL"
    nav = nt.to_nav(folders)
    assert nav["roots"] == ["2"]
    assert nav["folders"]["2.1"]["desc"] == "재무제표 BS/PL"

    import yaml
    nt.write_render(nav, index, tmp_path / "wiki")        # bottom-up: index.md then router.yaml
    router = yaml.safe_load((tmp_path / "wiki" / "router.yaml").read_text(encoding="utf-8"))
    # router.yaml = AMONG the top folders only: root + desc + size + a reference to its index.md
    assert set(router) == {"2. 재무"}
    assert router["2. 재무"]["n_pages"] == 1
    assert router["2. 재무"]["index"] == "nav/2. 재무/index.md"     # references the folder's index.md
    assert router["2. 재무"]["desc"] == "재무 자료"                  # read FROM that index.md
    assert "subfolders" not in router["2. 재무"]
    # the referenced index.md actually exists and carries that summary
    assert (tmp_path / "wiki" / "nav" / "2. 재무" / "index.md").read_text(encoding="utf-8").splitlines()[2] == "재무 자료"
    md = nt.render_folder_index("2", nav, index["pages"])
    assert "# 2. 재무" in md
    # subfolder is a relative link down to its own index.md (browsable tree)
    assert "[2.1. 재무제표](<2.1. 재무제표/index.md>)" in md


def test_nested_paths_mirror_tree(tmp_path):
    for d in ("2. 재무", "2. 재무/2.6. 투자", "2. 재무/2.6. 투자/2.6.3. 수익증권"):
        (tmp_path / d).mkdir(parents=True)
    folders = nt.build_folder_tree(tmp_path)
    nt.assign_pages(folders, {"pages": {"2.6.3. 수익증권__p": {"source": "XLSX"}}})
    folders = nt.prune_empty(folders)
    nav = nt.to_nav(folders)
    # provide the page's content file (as data_room would, in pages/)
    (tmp_path / "wiki" / "pages").mkdir(parents=True)
    (tmp_path / "wiki" / "pages" / "2.6.3. 수익증권__p.md").write_text("# p\n\n그리드 내용", encoding="utf-8")
    nt.write_render(nav, {"pages": {"2.6.3. 수익증권__p": {"title": "x"}}}, tmp_path / "wiki")
    leaf = tmp_path / "wiki" / "nav" / "2. 재무" / "2.6. 투자" / "2.6.3. 수익증권"
    assert (leaf / "index.md").exists()                    # folder index nested at its real path
    # the actual data file is placed IN the folder, with its content (the input), named locally
    assert (leaf / "p.md").read_text(encoding="utf-8") == "# p\n\n그리드 내용"
    assert "[p](<p.md>)" in (leaf / "index.md").read_text(encoding="utf-8")   # index links to it
    assert (tmp_path / "wiki" / "router.yaml").exists()
