"""CLI: ``python -m apps.agent "<question>"`` — demo the wiki agent, printing the routing trace.

With no arguments, runs a few sample questions. Needs ``data/wiki/`` built and the local
vLLM up (see ``src/stella_kb/llm.py``).
"""

from __future__ import annotations

import sys

from .core import run


def main(argv: list[str]) -> None:
    questions = argv or [
        "제5호 펀드의 2024년 총 운영비용은 얼마인가요?",
        "기업가치(Enterprise Value)는 얼마이고 어느 셀에서 오나요?",
        "관리수수료(operating revenue)는 어느 장표에 있나요?",
    ]
    for q in questions:
        print("=" * 78)
        print("Q:", q)
        print("-" * 78)
        print(run(q, verbose=True)["answer"])
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
