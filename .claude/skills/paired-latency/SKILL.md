---
name: paired-latency
description: Use when measuring the wall-clock latency impact of an agent-only change (e.g. curated routing skipping the router LLM) on this repo's wiki agent. Runs each question through both arms back-to-back, serially, so the per-question delta controls for the shared vLLM's load drift. Reports median per-question speedup. Ships paired_latency.py.
---

# Paired latency harness

The eval (`qa_eval`) records quality, **not** latency. To measure speed of an agent-only change,
time `core.run` directly — but the shared vLLM's load drifts minute to minute, so an absolute
"arm A took X, arm B took Y" comparison across two separate sweeps is unreliable. The fix is
**pairing**: for each question, run BOTH arms back-to-back and take the per-question delta. Load
drift hits both arms in a pair almost equally, so the delta is robust even when absolute times
are inflated (we saw a loaded vLLM push one question to 42s; the paired Δ was still clean).

## Method

1. **Serial, one question at a time** — no 8-worker concurrency. Concurrency measures throughput,
   not latency, and adds contention that swamps the signal.
2. **Toggle the arm by env between the two timed calls** of the same question. The repo's accessors
   read env fresh per call (`config.agent_routes_yaml`), and the routes loader is keyed by
   (path, mtime), so flipping `MNA_AGENT_ROUTES` mid-process actually switches behavior — verify
   this for any new lever before trusting it.
3. **Compile the graph once** (`build_app(store.index)`) and reuse it across all calls — graph
   build time is not what you're measuring.
4. **Report the median delta**, not the mean — robust to the occasional vLLM spike.
5. **Pick questions where the change actually fires.** Timing questions the change doesn't touch
   just adds noise. For curated routing, that's the `pages_opened`-differ set from a prior A/B run.

## Run it

```bash
# qids.json = list of question ids to time (e.g. the routing-differ set from agent-ab-eval)
PYTHONPATH=$PWD EVAL_DATASET=v0.2 \
  .venv/bin/python .claude/skills/paired-latency/paired_latency.py \
    --qids /tmp/diff_qids.json \
    --off 'MNA_AGENT_ROUTES=/tmp/routes_off.yaml' --on '-'
```

Prints per-question `OFF / ON / Δ` and a summary: median + mean per arm, and the median
per-question speedup with percent. Pair this with the structural proxy (how many router-LLM
calls the change skips) — the call-count reduction is load-independent; the wall-clock confirms
it translates to real time.

## Watch for

- A `/tmp` script needs `PYTHONPATH=$PWD` (repo root) or `import apps` fails.
- A loaded vLLM inflates ALL times; the paired Δ survives it, the absolute numbers don't — say so
  when reporting if the run coincided with heavy load.
- Results are timings only; nothing to commit.
