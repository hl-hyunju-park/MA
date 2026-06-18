"""Paired, error-excluded A/B analysis for the agent quality eval.

Usage:  python ab_analyze.py <ab_dir> <armA> <armB>  [--runs N]

Reads <ab_dir>/<arm>_r<k>/{answers,scores}.json for k=1..N. For each run pair it drops any
question that errored (`[ERROR] ...`) in EITHER arm — infra timeouts are not a quality signal —
and compares the surviving PAIRED set. Also reports the mechanism: on how many questions the
change altered pages_opened, and of those how many moved the rubric score. The eval is noisy
(shared vLLM); deltas under ~±0.1 are not signal — read the mechanism table alongside the means.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

args = [a for a in sys.argv[1:] if not a.startswith("--")]
runs = 2
if "--runs" in sys.argv:
    runs = int(sys.argv[sys.argv.index("--runs") + 1])
ab_dir, armA, armB = Path(args[0]), args[1], args[2]


def load(arm, r):
    d = ab_dir / f"{arm}_r{r}"
    sc = {s["id"]: s for s in json.loads((d / "scores.json").read_text())}
    an = {a["id"]: a for a in json.loads((d / "answers.json").read_text())}
    return sc, an


def errored(an, qid):
    return an[qid]["agent_answer"].startswith("[ERROR]")


print("=" * 60)
print(f"PAIRED, error-excluded:  {armA} (A) vs {armB} (B)   noise floor ~±0.1")
allA, allB = [], []
for r in range(1, runs + 1):
    try:
        asc, aan = load(armA, r)
        bsc, ban = load(armB, r)
    except FileNotFoundError:
        continue
    ids = [q for q in asc if q in bsc and not errored(aan, q) and not errored(ban, q)]
    am = mean(asc[q]["score"] for q in ids)
    bm = mean(bsc[q]["score"] for q in ids)
    allA += [asc[q]["score"] for q in ids]
    allB += [bsc[q]["score"] for q in ids]
    dropped = len(asc) - len(ids)
    print(f"\nRUN{r}: paired n={len(ids)} (dropped {dropped} errored)  "
          f"A {am:.3f}  B {bm:.3f}  Δ B-A {bm-am:+.3f}")
    moved = [(q, aan[q].get("doc"), asc[q]["score"], bsc[q]["score"]) for q in ids
             if set(aan[q]["pages_opened"]) != set(ban[q]["pages_opened"])
             and asc[q]["score"] != bsc[q]["score"]]
    changed = sum(set(aan[q]["pages_opened"]) != set(ban[q]["pages_opened"]) for q in ids)
    print(f"   routing differed on {changed}/{len(ids)}; of those score moved on {len(moved)}: "
          f"{[(q, f'{a:.1f}->{b:.1f}') for q, _, a, b in moved]}")

if allA:
    print("\n" + "=" * 60)
    print(f"POOLED over runs (paired clean items): A {mean(allA):.3f}  B {mean(allB):.3f}  "
          f"Δ B-A {mean(allB)-mean(allA):+.3f}  (n={len(allA)})")
