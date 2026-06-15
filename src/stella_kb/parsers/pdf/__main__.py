"""CLI smoke test:  python -m src.stella_kb.parsers.pdf <file.pdf> [--vision] [--max-pages N]

  (default)    strategy-routed parse (text → free; scan/diagram → vision)
  --vision     force vision describe on every page (gemma multimodal)
  --text       force pymupdf text only (no LLM)
  --max-pages  limit pages (vision smoke; avoids long full-doc runs)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from . import describe_pdf, detect_pdf_strategy, parse_pdf, parse_pdf_text


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    pdf = Path(argv[0])
    if not pdf.exists():
        print(f"no such file: {pdf}")
        return 1
    mode = "route"
    max_pages = None
    if "--vision" in argv:
        mode = "vision"
    elif "--text" in argv:
        mode = "text"
    if "--max-pages" in argv:
        max_pages = int(argv[argv.index("--max-pages") + 1])

    strat = detect_pdf_strategy(pdf)
    print(f"\nstrategy: {strat.strategy}  conf={strat.confidence}  ({strat.reason})")
    print(f"signals: {strat.signals}\n")

    if mode == "text":
        pages = parse_pdf_text(pdf)
    elif mode == "vision":
        pages, metrics = describe_pdf(pdf, max_pages=max_pages)
        print(f"metrics: pages={metrics.page_count} tables={len(metrics.table_payloads)} "
              f"fallback={metrics.fallback_pages or '-'} latency_ms={metrics.latency_ms}\n")
    else:
        pages = parse_pdf(pdf)

    print(f"== {len(pages)} page(s) ==")
    for p in pages[: (max_pages or 2)]:
        print(f"\n----- page {p.page} ({len(p.text)} chars) -----")
        print(p.text[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
