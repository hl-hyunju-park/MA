"""Format-normalizer logic — deterministic + offline (no LibreOffice, no network).

Pins the planning half (what gets converted, what's skipped) and the convert orchestration
(grouping, target verification, --replace) by injecting a fake soffice runner, so the real
binary is never invoked.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.stella_kb.convert import BACKENDS, CONVERSIONS, backend_for, convert, parse_map, plan


def _touch(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"")
    return p


def test_parse_map_normalizes_exts():
    assert parse_map("pptx:pdf, xls:xlsx") == {"pptx": "pdf", "xls": "xlsx"}
    assert parse_map(".DOC:.DOCX") == {"doc": "docx"}          # case + leading dots stripped
    with pytest.raises(ValueError):
        parse_map("xls")                                       # missing :dst


def test_plan_picks_mapped_exts_and_skips_litter(tmp_path):
    _touch(tmp_path / "deck.pptx")
    _touch(tmp_path / "sub" / "book.xls")
    _touch(tmp_path / "keep.txt")                              # unmapped ext
    _touch(tmp_path / ".DS_Store")                             # litter
    jobs = plan(tmp_path)
    srcs = {s.name for s, _ in jobs}
    assert srcs == {"deck.pptx", "book.xls"}
    dst = {s.name: d for s, d in jobs}
    assert dst["deck.pptx"].name == "deck.pdf"
    assert dst["book.xls"].name == "book.xlsx"


def test_plan_is_idempotent_when_target_exists(tmp_path):
    _touch(tmp_path / "book.xls")
    _touch(tmp_path / "book.xlsx")                             # already converted
    assert plan(tmp_path) == []
    assert len(plan(tmp_path, force=True)) == 1                # --force reconverts


def _fake_runners():
    """Runners that 'convert' by creating each expected target file; record (backend, ext, n)."""
    calls: list[tuple[str, str, int]] = []

    def make(backend):
        def runner(soffice, profile_url, target_ext, outdir, srcs):
            calls.append((backend, target_ext, len(srcs)))
            for s in srcs:
                (outdir / (s.stem + "." + target_ext)).write_bytes(b"converted")
        return runner

    return {b: make(b) for b in ("soffice", "image", "hwp")}, calls


def test_backend_routing():
    assert backend_for(".xls") == "soffice" and backend_for("docx") == "soffice"
    assert backend_for(".tif") == "image" and backend_for("jpg") == "image"
    assert backend_for(".hwp") == "hwp"
    assert set(BACKENDS.values()) <= {"image", "hwp"}          # soffice is the implicit default


def test_convert_batches_by_backend_dir_ext(tmp_path):
    _touch(tmp_path / "a.xls")
    _touch(tmp_path / "b.xls")                                 # same backend+dir+ext -> one batch
    _touch(tmp_path / "deck.pptx")                             # soffice, different ext -> own batch
    _touch(tmp_path / "scan.tif")                              # image backend -> own batch
    runners, calls = _fake_runners()
    res = convert(plan(tmp_path), runners=runners, log=lambda *_: None)
    assert sorted(calls) == [("image", "pdf", 1), ("soffice", "pdf", 1), ("soffice", "xlsx", 2)]
    assert len(res["converted"]) == 4 and not res["failed"]
    assert (tmp_path / "a.xlsx").exists() and (tmp_path / "scan.pdf").exists()


def test_convert_replace_removes_source_only_after_success(tmp_path):
    _touch(tmp_path / "book.xls")
    runners, _ = _fake_runners()
    convert(plan(tmp_path), replace=True, runners=runners, log=lambda *_: None)
    assert not (tmp_path / "book.xls").exists()
    assert (tmp_path / "book.xlsx").exists()


def test_image_backend_really_makes_a_pdf(tmp_path):
    # offline, no LibreOffice: exercises the real Pillow image runner end-to-end
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    Image.new("RGB", (8, 8), "white").save(tmp_path / "scan.tif")
    res = convert(plan(tmp_path), log=lambda *_: None)         # default runners (real image backend)
    assert len(res["converted"]) == 1 and not res["failed"]
    pdf = (tmp_path / "scan.pdf").read_bytes()
    assert pdf.startswith(b"%PDF")


def test_convert_dry_run_touches_nothing(tmp_path):
    _touch(tmp_path / "book.xls")

    def boom(*_a, **_k):                                       # must not be called on a dry run
        raise AssertionError("runner invoked during dry run")

    res = convert(plan(tmp_path), dry_run=True, runners={"soffice": boom}, log=lambda *_: None)
    assert res == {"converted": [], "failed": []}
    assert not (tmp_path / "book.xlsx").exists()


def test_failed_when_target_not_produced(tmp_path):
    _touch(tmp_path / "book.xls")

    def noop(*_a, **_k):                                       # runs but produces no output
        pass

    res = convert(plan(tmp_path), runners={"soffice": noop}, log=lambda *_: None)
    assert res["failed"] and not res["converted"]


def test_default_map_lands_in_ingestable_formats():
    # every target is one of the two formats the pipeline reads
    assert set(CONVERSIONS.values()) == {"pdf", "xlsx"}
    assert CONVERSIONS["pptx"] == "pdf" and CONVERSIONS["xls"] == "xlsx"
    assert CONVERSIONS["doc"] == CONVERSIONS["docx"] == CONVERSIONS["hwp"] == "pdf"
    assert CONVERSIONS["jpg"] == CONVERSIONS["tif"] == "pdf"


def test_plan_raises_on_target_collision(tmp_path):
    # doc + docx in the same dir both map to <stem>.pdf — must fail loudly, not clobber
    _touch(tmp_path / "report.doc")
    _touch(tmp_path / "report.docx")
    with pytest.raises(ValueError, match="collision"):
        plan(tmp_path)
