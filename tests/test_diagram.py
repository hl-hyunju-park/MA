"""parsers.pdf.diagram — deterministic legend-coverage detection for structure diagrams.

The vision model reliably transcribes a diagram's *legend* but, on dense org charts, skips the
per-box legend binding (which boxes are 흰색/★/노란색). These tests pin the offline detection of
that gap (``parse_legend`` / ``covered_keys`` / ``missing_categories``) and the merge — the one
vision call (``augment_diagram``) is exercised against a stub, no network.
"""

from __future__ import annotations

from src.stella_kb.parsers.pdf import diagram

# A real-shaped CAESAR FDD2 diagram: full legend, but only ONE box (CP LLC) actually tagged
# 노란색 in the connection list; 흰색 / ★ / 점선 are declared in the legend yet bound to no box.
_UNDER_COVERED = r"""[다이어그램]
**범례**:
- 회색 박스 $\rightarrow$ Entities/SPV (Incorporated)
- 흰색 박스 $\rightarrow$ Entities/SPV (To Be Set-up)
- $\star$ 기호 $\rightarrow$ Entities that require bank settlement
- 노란색 박스 $\rightarrow$ Entity paying Management & Manager fee
- 점선 테두리 $\rightarrow$ Consolidated FS

**Apex**: Tang Family

**연결 목록**:
- CP Holdings I LLC $\rightarrow$ CP LLC (노란색) : 100.0%
- CP (AP) GP Limited $\rightarrow$ New Fund III GP : (연결선)
---
Note[1]: …
"""

# A well-covered diagram: every non-gray legend category has at least one tagged box.
_COVERED = r"""[다이어그램]
**범례**
- 회색 박스 $\rightarrow$ Existing
- 녹색 박스 $\rightarrow$ Target

**박스 목록**
- Silver Treasure Inc. (회색=Seychelles)
- CP LLC (녹색=Cayman)
"""


def test_parse_legend_extracts_keys_and_meaning():
    legend = diagram.parse_legend(_UNDER_COVERED)
    assert set(legend) == {"회색", "흰색", "★", "노란색", "점선"}
    assert "To Be Set-up" in legend["흰색"]
    assert "bank settlement" in legend["★"]


def test_covered_keys_only_counts_tagged_boxes():
    covered = diagram.covered_keys(_UNDER_COVERED)
    assert "노란색" in covered          # CP LLC (노란색) is tagged in the body
    assert "흰색" not in covered         # declared in legend, but no box carries it
    assert "★" not in covered
    assert "점선" not in covered


def test_missing_categories_flags_gap_and_ignores_gray():
    missing = diagram.missing_categories(_UNDER_COVERED)
    assert set(missing) == {"흰색", "★", "점선"}   # gray excluded; 노란색 is covered


def test_well_covered_diagram_has_no_missing():
    assert diagram.missing_categories(_COVERED) == []
    assert diagram.has_diagram(_COVERED)


def test_no_diagram_is_noop():
    plain = "# Some page\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert not diagram.has_diagram(plain)
    assert diagram.missing_categories(plain) == []


def test_diagram_terms_extracts_box_and_connection_entities():
    """Box-list members, connection endpoints, and the Apex become routable alias terms; the
    colour/percentage annotations are stripped and legend/non-numeric lines are excluded."""
    box_terms = diagram.diagram_terms(_COVERED)
    assert "Silver Treasure Inc." in box_terms   # from 박스 목록, '(회색=Seychelles)' stripped
    assert "CP LLC" in box_terms

    conn_terms = diagram.diagram_terms(_UNDER_COVERED)
    assert "Tang Family" in conn_terms                 # **Apex**
    assert "CP Holdings I LLC" in conn_terms           # connection-line LHS
    assert "CP LLC" in conn_terms                       # connection-line RHS, '(노란색)' stripped
    assert "New Fund III GP" in conn_terms
    # legend meanings and the colour annotations never become terms
    assert not any("Entities/SPV" in t for t in conn_terms)
    assert not any("노란색" in t for t in conn_terms)


def test_diagram_terms_empty_without_diagram():
    assert diagram.diagram_terms("# Plain\n\n- a normal bullet\n- another\n") == []


def test_diagram_terms_scope_resets_after_section():
    """A bullet in a later section (notes/links) must not leak in as an entity."""
    md = (_COVERED + "\n## Links\n- 엑셀 원천 (교차검증 대상): foo\n")
    terms = diagram.diagram_terms(md)
    assert not any("엑셀 원천" in t for t in terms)


def test_merge_augmentation_inserts_before_footnote():
    block = "**특수표시 박스 (보강)**\n- 흰색(To Be Set-up): New Fund III GP"
    merged = diagram.merge_augmentation(_UNDER_COVERED, block)
    # the recovered block lands inside the diagram region, before the Note footer
    assert "특수표시 박스 (보강)" in merged
    assert merged.index("특수표시 박스") < merged.index("Note[1]")


def test_augment_diagram_calls_vision_and_merges(monkeypatch):
    """The one vision-touching path: stub the model to return the recovered grouping; assert it's
    merged and that the gap closes."""
    recovered = ("**특수표시 박스 (보강)**\n"
                 "- 흰색(To Be Set-up): New Fund III GP\n"
                 "- ★(bank settlement): CP LLC\n"
                 "- 점선(Consolidated FS): CP Holdings I LLC")
    from src.stella_kb.parsers.pdf import vision

    calls = {"n": 0}

    def fake_invoke(**kwargs):
        calls["n"] += 1
        assert "특수표시" in kwargs["prompt"]  # the focused re-prompt
        return recovered

    monkeypatch.setattr(vision, "invoke_vision", fake_invoke)
    monkeypatch.setattr(vision, "get_or_compute", lambda *, model, system, user, compute: compute())

    out = diagram.augment_diagram(_UNDER_COVERED, image_path="/x.png", model="m")
    assert calls["n"] == 1
    assert "특수표시 박스 (보강)" in out
    # after merge, the three previously-missing categories are now bound to boxes
    assert diagram.missing_categories(out) == []


def test_augment_diagram_noop_when_covered(monkeypatch):
    from src.stella_kb.parsers.pdf import vision
    monkeypatch.setattr(vision, "invoke_vision",
                        lambda **k: (_ for _ in ()).throw(AssertionError("should not call vision")))
    assert diagram.augment_diagram(_COVERED, image_path="/x.png", model="m") == _COVERED
