"""Thin OpenAI-compatible client for the local vLLM endpoint, plus the one LLM use the
retrieval strategy actually sanctions: **words -> nodes** (resolve a KO/EN query term to a
Metric id), never evidence retrieval — see CLAUDE.md "Retrieval strategy".

Config via env (defaults point at the shared local vLLM server):
    STELLA_LLM_URL    base URL, default http://localhost:33333/v1
    STELLA_LLM_MODEL  served model name, default gemma-4-31B-it

The server runs on this host, so use ``localhost``. Stdlib only (urllib) — no new
dependency. The endpoint is OpenAI-compatible, so swapping in a hosted API is just two
env vars.
"""

from __future__ import annotations

import json
import os
import urllib.request

from .graph.metrics import METRICS, METRIC_IDS
from .prompts import load as load_prompt

BASE_URL = os.environ.get("STELLA_LLM_URL", "http://localhost:33333/v1")
MODEL = os.environ.get("STELLA_LLM_MODEL", "gemma-4-31B-it")


def chat(messages: list[dict], temperature: float = 0.0, max_tokens: int = 512,
         timeout: float = 60.0) -> str:
    """One chat-completions round trip; returns the assistant text."""
    payload = json.dumps({
        "model": MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"]


def _catalog() -> str:
    """Closed-vocabulary catalog handed to the model: id + EN/KO labels + aliases."""
    lines = []
    for m in METRICS:
        names = [m.label_en] + ([m.label_ko] if m.label_ko else []) + list(m.aliases)
        lines.append(f"- {m.id}: {' | '.join(names)}")
    return "\n".join(lines)


def resolve_metric(term: str, timeout: float = 60.0) -> dict:
    """Map a free-text term (Korean or English) to a Metric id from the closed set.

    Whitelist-guarded (OpenKB pattern): the model is given only the existing ids and must
    return one of them or ``null`` — a returned id outside ``METRIC_IDS`` is rejected to
    ``null`` rather than trusted, so no hallucinated node can leak through.
    """
    sys = load_prompt("resolve_metric_system")
    user = f"Catalog:\n{_catalog()}\n\nTerm: {term!r}\nJSON:"
    raw = chat([{"role": "system", "content": sys}, {"role": "user", "content": user}],
               max_tokens=80, timeout=timeout)
    s = raw.strip()
    if "```" in s:                       # strip ```json fences if the model adds them
        s = s.split("```")[1].lstrip("json").strip() if s.count("```") >= 2 else s.strip("`")
    start, end = s.find("{"), s.rfind("}")
    try:
        obj = json.loads(s[start:end + 1])
    except (ValueError, json.JSONDecodeError):
        return {"id": None, "confidence": 0.0, "raw": raw}
    if obj.get("id") not in METRIC_IDS:  # guard: reject anything off-whitelist
        obj["id"] = None
    return obj


if __name__ == "__main__":
    print(f"endpoint: {BASE_URL}  model: {MODEL}\n")
    for term in ["관리수수료", "carry", "discount rate", "성과보수", "EV", "누적 AUM",
                 "퇴직급여충당부채", "그냥 아무 말"]:
        r = resolve_metric(term)
        print(f"  {term:16s} -> {str(r.get('id')):26s} (conf {r.get('confidence')})")
