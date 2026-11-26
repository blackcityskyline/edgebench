# Instructions for worker agents

> If your prompt says to read `RUN_ME.md`, you are an **operator**, not a worker: follow `RUN_ME.md` instead of the rules below.

You are a worker on `edgebench`, a research bench for testing trading ideas on historical data. The project rules are in `docs/CONTRACT.md`. Read the sections your task points to before writing code.

## How you are started

The runner starts you with one fixed prompt: execute the task named in it. You never receive a custom prompt. Everything you need is in the task file `tasks/T-NNN-*.md` and the files listed in its `context_files`. If `.runner/feedback.md` exists, read it first: it holds the failure log of your previous attempt.

## Rules

1. Edit only paths listed in the task's `allowed_paths`. Protected paths (listed in `src/edgebench/runner/protected.py`) are off limits even if a task lists them: `gates/`, `docs/`, `tasks/`, `tests/fixtures/`, `src/edgebench/contracts/`, `src/edgebench/runner/`, `holdout/`, `.github/`, `AGENTS.md`, `ARCHITECT.md`.
2. Never change a test or a gate to make it pass. If a test looks wrong, say so in the escalation (below) instead of editing it.
3. Never read, create or request data from the holdout split. Never set `EDGEBENCH_HOLDOUT_TOKEN`.
4. Never write secrets, API keys, tokens or data files into the repository. Use environment variables. The repository is public.
5. No new dependencies unless the task lists `pyproject.toml` in `allowed_paths`.
6. Causality: code may use only information available at the decision time (`docs/CONTRACT.md` section 2.1). Objects have `formed_at` and `known_at`; use nothing before `known_at`.
7. Python 3.11+, full type hints, small functions, docstrings for public ones. Code must pass `ruff` and `mypy`.
8. Write tests with known answers (hand-built bars, not random data) next to the code.

## Finishing

Run the task's `acceptance` commands and `python -m edgebench.cli gates --quick`. Stop when they pass. Do not commit or push; the runner does that.

If you cannot finish (contradiction in the contract, missing information, a protected file needs a change), write `.runner/escalation.md` with: what you tried, the exact error or contradiction, and the one question the architect must answer. Then stop.
