"""Property-graph KB: formula DAG (extract) -> semantic graph + metrics -> query.

Kept import-light (no re-exports): `llm.py` imports `graph.metrics`, so importing this
package must not pull in `query` (which imports `llm`) — avoids a cycle.
"""
