"""Normalize a corpus's file formats *before* ingest — legacy office files → the two formats the
pipeline already reads (``.xlsx`` via ``dump_md``, ``.pdf`` via the vision parser).

The v0.3 data room ships nine extensions; the parsers handle two. This pass collapses every other
format into one of those two so the ingest only has to know about ``.pdf`` and ``.xlsx``:

    pptx, doc, docx, hwp, jpg, tif → pdf   (join the PDF vision path)
    xls                            → xlsx  (join the dump_md path)

Most formats go through LibreOffice headless, but two get a dedicated backend (see ``BACKENDS``):
raster images (``jpg``/``tif``…) render via **Pillow** — LO's TIFF import chokes on the CCITT-G4
fax scans common in scanned tax docs — and **HWP v5** (Hangul, no working LO 7.x import filter)
lifts to ODT via **pyhwp** then renders to PDF with LO.

It is **non-destructive** by default (the converted file lands next to the original; pass
``--replace`` to delete the source after a verified conversion), **idempotent** (a file whose
target already exists is skipped — so re-running only converts what's new), and **offline** (no
LLM). Add a format by extending ``CONVERSIONS`` (target ext) and, if LibreOffice can't read it,
``BACKENDS`` (which converter) — or pass ``--map`` for a one-off.

    python -m src.stella_kb.convert                 # dry-run plan over the default root (offline)
    python -m src.stella_kb.convert --apply         # actually convert
    python -m src.stella_kb.convert <root> --apply --replace
    python -m src.stella_kb.convert --map doc:docx,xls:xlsx --apply
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from .config import convert_root, hwp5odt_bin, soffice_bin

# Default source-ext (lower, no dot) → target-ext. Everything lands in one of the two formats the
# pipeline ingests: ``.xlsx`` (dump_md) or ``.pdf`` (vision parser). Spreadsheets stay spreadsheets;
# every document/image format becomes a PDF for the vision path. Extend here as new formats appear.
CONVERSIONS: dict[str, str] = {
    "pptx": "pdf",
    "xls": "xlsx",
    "doc": "pdf",
    "docx": "pdf",
    "hwp": "pdf",
    "jpg": "pdf",
    "jpeg": "pdf",
    "tif": "pdf",
    "tiff": "pdf",
}

# Per-source-ext converter backend. LibreOffice handles the office formats, but two need their own:
# raster images (LO's TIFF import chokes on CCITT-G4 fax scans) go through Pillow, and HWP v5 (no
# working import filter in LO 7.x) goes through pyhwp (hwp → odt → LO pdf). Absent ext ⇒ "soffice".
BACKENDS: dict[str, str] = {
    "jpg": "image", "jpeg": "image", "tif": "image", "tiff": "image",
    "hwp": "hwp",
}

# macOS data-room litter — never a conversion source.
SKIP_NAMES = {".DS_Store"}

Job = tuple[Path, Path]                       # (source, target)
Runner = Callable[[str, str, str, Path, list[Path]], None]


def backend_for(ext: str) -> str:
    """Which converter backend handles a source extension (lower, no dot). Default: ``soffice``."""
    return BACKENDS.get(ext.lower().lstrip("."), "soffice")


def parse_map(spec: str) -> dict[str, str]:
    """``"pptx:pdf,xls:xlsx"`` → ``{"pptx": "pdf", "xls": "xlsx"}``. Exts are normalized to
    lower-case without a leading dot."""
    out: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"bad --map entry {pair!r} (expected src:dst, e.g. xls:xlsx)")
        src, dst = pair.split(":", 1)
        out[src.strip().lower().lstrip(".")] = dst.strip().lower().lstrip(".")
    return out


def plan(root: Path, conversions: dict[str, str] = CONVERSIONS, *, force: bool = False) -> list[Job]:
    """Walk ``root`` and return the (source, target) pairs to convert. A target that already exists
    is skipped unless ``force`` (idempotent re-runs). Deterministic order (sorted paths)."""
    jobs: list[Job] = []
    for src in sorted(root.rglob("*")):
        if not src.is_file() or src.name in SKIP_NAMES:
            continue
        target_ext = conversions.get(src.suffix.lower().lstrip("."))
        if not target_ext:
            continue
        dst = src.with_suffix("." + target_ext)
        if dst.exists() and not force:
            continue
        jobs.append((src, dst))

    # Guard: two sources collapsing to one target (e.g. report.doc + report.docx → report.pdf)
    # would silently clobber. Fail loudly rather than lose a file — disambiguate the source first.
    seen: dict[Path, Path] = {}
    clashes: list[tuple[Path, Path]] = []
    for src, dst in jobs:
        if dst in seen:
            clashes.append((seen[dst], src))
        seen[dst] = src
    if clashes:
        detail = "\n".join(f"  {a.name} + {b.name}  (both target {a.with_suffix('').name})"
                           for a, b in clashes)
        raise ValueError(f"{len(clashes)} target-name collision(s); rename a source first:\n{detail}")
    return jobs


def _soffice_runner(soffice: str, profile_url: str, target_ext: str,
                    outdir: Path, srcs: list[Path]) -> None:
    """One headless LibreOffice batch: convert every ``srcs`` file into ``outdir`` as ``target_ext``.
    LibreOffice names each output ``<stem>.<target_ext>`` in ``outdir``, matching ``plan``'s target."""
    cmd = [soffice, "--headless", f"-env:UserInstallation={profile_url}",
           "--convert-to", target_ext, "--outdir", str(outdir), *(str(s) for s in srcs)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _image_runner(soffice: str, profile_url: str, target_ext: str,
                  outdir: Path, srcs: list[Path]) -> None:
    """Raster image → PDF via Pillow (one PDF page per frame; handles multi-page TIFFs and the
    CCITT-G4 fax scans LibreOffice can't import)."""
    from PIL import Image
    for s in srcs:
        im = Image.open(s)
        frames = []
        try:
            while True:
                frames.append(im.convert("RGB"))
                im.seek(im.tell() + 1)
        except EOFError:
            pass
        frames[0].save(outdir / (s.stem + "." + target_ext), "PDF",
                       save_all=True, append_images=frames[1:], resolution=200.0)


def _hwp_runner(soffice: str, profile_url: str, target_ext: str,
                outdir: Path, srcs: list[Path]) -> None:
    """HWP v5 → PDF in two steps: pyhwp's ``hwp5odt`` lifts the doc to ODT, then LibreOffice renders
    that ODT to ``target_ext``. The ODT keeps the source stem, so LO's output name matches the plan."""
    hwp_bin = hwp5odt_bin()
    if shutil.which(hwp_bin) is None and os.sep not in hwp_bin:
        venv = Path(sys.executable).parent / hwp_bin     # installed alongside the venv python
        if venv.exists():
            hwp_bin = str(venv)
    for s in srcs:
        with tempfile.TemporaryDirectory(prefix="hwp_") as td:
            odt = Path(td) / (s.stem + ".odt")
            subprocess.run([hwp_bin, "--output", str(odt), str(s)],
                           check=True, capture_output=True, text=True)
            _soffice_runner(soffice, profile_url, target_ext, outdir, [odt])


# backend name → runner. Inject a replacement via ``convert(..., runners=...)`` in tests.
DEFAULT_RUNNERS: dict[str, Runner] = {
    "soffice": _soffice_runner,
    "image": _image_runner,
    "hwp": _hwp_runner,
}


def convert(jobs: Iterable[Job], *, soffice: str | None = None, replace: bool = False,
            dry_run: bool = False, runners: dict[str, Runner] | None = None,
            log: Callable[[str], None] = print) -> dict[str, list[Job]]:
    """Run ``jobs`` through their per-format backend (``BACKENDS`` → soffice/image/hwp). Batches by
    (backend, target dir, target ext) to minimize process spawns. Verifies each target exists before
    counting it converted; on ``replace`` removes the source only after that check. Returns
    ``{"converted": [...], "failed": [...]}``."""
    jobs = list(jobs)
    result: dict[str, list[Job]] = {"converted": [], "failed": []}
    if dry_run or not jobs:
        for src, dst in jobs:
            log(f"    would convert  {src.name}  ->  {dst.name}")
        return result

    soffice = soffice or soffice_bin()
    runners = runners or DEFAULT_RUNNERS
    # A unique, isolated LibreOffice profile so this run can't clash with a desktop session's lock.
    with tempfile.TemporaryDirectory(prefix="lo_convert_") as profile:
        profile_url = Path(profile).as_uri()
        groups: dict[tuple[str, Path, str], list[Job]] = defaultdict(list)
        for src, dst in jobs:
            backend = backend_for(src.suffix)
            groups[(backend, dst.parent, dst.suffix.lstrip("."))].append((src, dst))

        for (backend, outdir, target_ext), group in groups.items():
            runner = runners.get(backend)
            if runner is None:
                log(f"    !! no runner for backend {backend!r}")
                result["failed"].extend(group)
                continue
            try:
                runner(soffice, profile_url, target_ext, outdir, [s for s, _ in group])
            except Exception as e:                       # soffice/pyhwp/PIL failures all land here
                stderr = getattr(e, "stderr", None)
                log(f"    !! {backend} failed for {outdir} (.{target_ext}): {stderr or e}")
                result["failed"].extend(group)
                continue
            for src, dst in group:
                if not dst.exists():
                    log(f"    !! expected output missing: {dst}")
                    result["failed"].append((src, dst))
                    continue
                if replace:
                    src.unlink()
                result["converted"].append((src, dst))
                log(f"    {'replaced' if replace else 'converted'}  {src.name}  ->  {dst.name}")
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Normalize corpus file formats via LibreOffice headless.")
    ap.add_argument("root", nargs="?", default=None,
                    help="corpus root to walk (default: config convert.root)")
    ap.add_argument("--map", dest="map_spec", default=None,
                    help='conversion map, e.g. "pptx:pdf,xls:xlsx" (default: built-in CONVERSIONS)')
    ap.add_argument("--apply", action="store_true", help="actually convert (default is a dry run)")
    ap.add_argument("--replace", action="store_true", help="delete each source after a verified convert")
    ap.add_argument("--force", action="store_true", help="reconvert even if the target already exists")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else convert_root()
    conversions = parse_map(args.map_spec) if args.map_spec else CONVERSIONS
    if not root.exists():
        print(f"!! root not found: {root}")
        return 1

    jobs = plan(root, conversions, force=args.force)
    rule = ", ".join(f"{s}->{d}" for s, d in conversions.items())
    print(f"==> root: {root}")
    print(f"==> map:  {rule}")
    print(f"==> {len(jobs)} file(s) to convert" + ("" if args.apply else "  (dry run — pass --apply)"))

    res = convert(jobs, replace=args.replace, dry_run=not args.apply)
    if args.apply:
        print(f"==> converted {len(res['converted'])}, failed {len(res['failed'])}")
        return 1 if res["failed"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
