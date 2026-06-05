"""Vectorless wiki KB: workbook -> Markdown grids -> LLM parse -> wiki pages + index.

Pipeline: dump_md -> parse_llm -> compile -> index (see scripts/run_pipeline.sh).
Kept import-light (no re-exports) so `llm.py` -> `graph.metrics` stays cycle-free.
"""
