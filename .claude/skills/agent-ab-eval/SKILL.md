---
name: agent-ab-eval
description: Use when measuring whether an agent-only change (routing, retrieval, prompt, a config flag) helps or hurts answer quality on a built wiki — A/B it against a baseline. Holds the built pages FIXED, toggles only the agent via env, runs each arm multiple times, EXCLUDES infra timeouts instead of scoring them 0, and reports paired deltas plus a mechanism check. Ships ab_eval.sh + ab_analyze.py.
---

# Agent A/B eval (quality)

Measure an **agent-only** change against a baseline without conflating it with a wiki rebuild.
The shared vLLM is non-deterministic (continuous batching), so single-run deltas under **~±0.1
are not signal** — average several runs per arm and look at the *mechanism*, not just the score.

## The five rules that keep the number honest

1. **Hold the built pages FIXED.** Do not rebuild between arms — a rebuild re-runs
   `structure_section` per page and moves the score on its own. Same `data/<v>/wiki`, both arms.
2. **Toggle ONLY the agent, via env.** The change must be a runtime switch, not a code edit
   between runs. Example lever: curated routing on/off is `MNA_AGENT_ROUTES` pinned to an empty
   file (→ `route_lookup` returns `[]` → pure-LLM router) vs unset (→ committed `routes.yaml`).
   A flag lever is its `config.py` env (e.g. `MNA_DET_RETRIEVE=1`).
3. **Run each arm ≥2×.** Compare means over runs, not a single pass.
4. **EXCLUDE infra errors — never score them 0.** `[ERROR] TimeoutError` is the shared vLLM
   overloading, not a quality signal. Scoring those 0 silently sinks whichever arm got unlucky
   (we once saw a fake −0.116 that was 24 timeouts in one arm). Drop any question that errored in
   *either* arm of a run, compare the surviving **paired** set, and report how many were dropped.
5. **Check the mechanism, not just the score.** The eval records `pages_opened` per question.
   Report on how many questions the change actually altered routing/retrieval, and of those, how
   many moved the score. "Changed the path on 29/54, moved the score on 0" is the convincing
   evidence that a latency optimization is quality-neutral.

## Run it

`ab_eval.sh` runs each arm × N runs (eval only), then judges every answer set identically.
Define arms as `name=ENV_PIN` pairs (`ENV_PIN` is `-` for the baseline/default config):

```bash
AB_DIR=data/eval/ab RUNS=2 EVAL_DATASET=v0.2 \
  .claude/skills/agent-ab-eval/ab_eval.sh \
    off='MNA_AGENT_ROUTES=/tmp/routes_off.yaml' on='-'
# then:
.venv/bin/python .claude/skills/agent-ab-eval/ab_analyze.py data/eval/ab off on
```

`ab_analyze.py` prints, per run-pair: paired error-excluded means, Δ vs the ±0.1 noise floor,
breakdowns by capability/doc, and the routing-differ × score-moved mechanism table.

## Watch for

- **vLLM overload mid-run** inflates timeouts. Run arms **sequentially** (one process at a time)
  — two concurrent 8-worker evals doubled the load and produced the timeout storm. If an arm
  comes back with many `[ERROR]`s, the vLLM was busy; re-run that arm rather than trusting it.
- `MNA_AGENT_ROUTES` (and other env pins) are **single-dataset** — fine for an eval that targets
  one `EVAL_DATASET`, wrong for multi-dataset serving.
- Artifacts land under `AB_DIR` (inside `data/`, gitignored, regenerable) — nothing to commit.
