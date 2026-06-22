"""Composable prompt loader — ``{{include}}`` / ``{{!}}`` directives (offline, deterministic).

The synthesizer prompt is assembled from blocks/; these assert the loader inlines includes,
drops maintainer comments, never leaks a directive to the model, and that plain prompts (no
directives) still load unchanged.
"""

from __future__ import annotations

import pytest

from apps.agent import prompts
from apps.agent.prompts import load


def test_synthesizer_assembles_without_leaking_directives():
    text = load("synthesizer")
    # no directive survives into the model-facing prompt
    assert "{{include" not in text and "{{!" not in text
    # every block's section header is present, in order
    for header in ("# 규칙", "## 최종 계산", "## 검증 불가", "## 감사 경고", "# 출력 형식"):
        assert header in text
    assert text.index("# 규칙") < text.index("## 최종 계산") < text.index("# 출력 형식")


def test_include_inlines_block_text():
    out = prompts._expand("머리말\n{{include: blocks/synth_output}}\n꼬리말")
    assert "머리말" in out and "꼬리말" in out
    assert "# 출력 형식" in out          # the included block's content
    assert "{{include" not in out


def test_comment_lines_are_dropped():
    out = prompts._expand("{{! 유지보수 메모 — 모델에 보이면 안 됨 }}\n본문")
    assert out == "본문"


def test_plain_prompt_unchanged():
    # a prompt with no directives loads as its stripped raw text
    assert load("verifier") == prompts._raw("verifier").strip()


def test_include_cycle_is_depth_guarded(monkeypatch):
    # a self-referential include must raise, not recurse forever
    monkeypatch.setattr(prompts, "_raw", lambda name: "{{include: loop}}")
    with pytest.raises(RecursionError):
        prompts._expand("{{include: loop}}")
