"""The graph's id grammar, in one place.

Two id shapes run through the property graph and were previously split open by ad-hoc
``.split(...)`` calls scattered across modules (with subtle inconsistencies — some used
``[1]``, some ``[-1]``):

* **Cell id** ``"Sheet!REF"`` — e.g. ``"DCF!K59"`` (note: the sheet may itself contain
  spaces/Korean, but never ``!``).
* **Typed node id** ``"Type:name"`` — e.g. ``"Metric:equity_value"``, ``"Sheet:DCF"``,
  ``"Fund:제8호"``, ``"Period:2024"``.

Keep all parsing/forming of those here so the grammar has a single source of truth.
"""

from __future__ import annotations


def cell_id(sheet: str, ref: str) -> str:
    """Form a ``"Sheet!REF"`` cell id."""
    return f"{sheet}!{ref}"


def sheet_of(cell_id: str) -> str:
    """The sheet of a ``"Sheet!REF"`` cell id (``"DCF!K59"`` -> ``"DCF"``)."""
    return cell_id.split("!", 1)[0]


def nid(node_type: str, name: str) -> str:
    """Form a ``"Type:name"`` node id (``nid("Metric", "wacc")`` -> ``"Metric:wacc"``)."""
    return f"{node_type}:{name}"


def name_of(node_id: str) -> str:
    """The name part of a ``"Type:name"`` node id (``"Metric:wacc"`` -> ``"wacc"``).

    A bare cell id (no ``":"``) is returned unchanged, so this is safe to call on the mixed
    cell/Sheet endpoints that ``DEFINED_IN`` produces.
    """
    return node_id.split(":", 1)[-1]
