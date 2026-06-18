---
name: module-run-script
description: Use when adding or substantially changing a runnable Python module under src/ or apps/ in this repo. Enforces the project convention that executable code always ships with an executable wrapper — a scripts/run_<name>.sh, a __main__ smoke-print, and a deterministic offline test — so anything we build can be run and verified the same way (scripts/run_pipeline.sh, run_eval.sh, etc.).
---

# Module + run-script convention

In this repo, **code that can be executed always ships with the means to execute it.** Every
build/serve/eval entry point has a `scripts/run_*.sh` wrapper and a `python -m ...` `__main__`
smoke; tests are deterministic + offline by default. When you add or meaningfully change a
runnable module, deliver all four pieces below in the same change — don't leave the runner for
"later".

## Checklist (do all that apply)

1. **`__main__` smoke.** The module runs from the repo root via `python -m <dotted.path>` and
   prints something verifying it loaded (a count, a resolved path, a tiny end-to-end result).
   Keep it cheap and offline where possible; gate live-LLM behavior behind a flag.

2. **`scripts/run_<name>.sh` wrapper.** A thin, idempotent shell entry point. Follow the house
   style (see `scripts/run_eval.sh`): `set -euo pipefail`; `cd "$(dirname "$0")/.."` so it works
   from any cwd; `PY="${PY:-.venv/bin/python}"`; surface required config as overridable env with
   `: "${VAR:=default}"`; print what it's about to do; pre-flight checks (artifact exists, vLLM
   reachable) before the real work; `exec "$PY" -m <module> "$@"`. Use the template:
   `.claude/skills/module-run-script/run_template.sh`.

3. **Config through `config.py`, not bare `os.getenv`.** New knobs resolve env > config.yaml >
   default via an accessor in `src/stella_kb/config.py`; secrets stay in `.env`. The run script
   exports the env the module reads (the pipeline scripts inherit exported env on purpose).

4. **Deterministic offline test in `tests/`.** Covers the logic without network. Live-LLM
   end-to-end checks are marked `@pytest.mark.llm` and skipped unless `--run-llm`. Fixtures must
   skip cleanly when build artifacts are absent so a fresh checkout still runs `pytest` green.

## Acceptance

- `python -m <module>` works from `MA/` and prints its smoke line.
- `scripts/run_<name>.sh` runs the module with sane defaults and fails fast with a clear message
  if a prerequisite (artifact / vLLM) is missing.
- `pytest -q` stays green offline; any live test is `@pytest.mark.llm`-gated.
- A new tunable is reachable via a `config.py` accessor (env > yaml > default), not inline getenv.

Mirror the surrounding scripts' tone and structure — a new runner should read like `run_eval.sh`,
not like a fresh invention.
