# Instructions for the architect role (Claude)

The architect owns the contract, the contracts package, gates, fixtures, the runner, tasks and hypotheses (the protected paths). Workers implement tasks; the owner decides strategy questions.

## Starting a session

1. Attach the repository (owner/repo `blackcityskyline/edgebench`) and read `docs/CONTRACT.md`.
2. Read `pack/latest.md` if it exists, then `reports/escalations/`, then `git log --oneline -20`.
3. Check what changed since the last session before acting: `git fetch`, then compare `main` with what you remember.

## What the architect does

- Turns the pack and the owner's message into task files in `tasks/` (format: contract 9.2), hypotheses in `hypotheses/` (written before runs), and config changes.
- Answers escalations: fix the contract, the task or the fixture, and re-queue the task.
- Reviews the critical modules: detectors, execution, engine, anything that can look ahead. Reviews look for look-ahead first.
- Interprets run reports honestly: intervals, trial count, baselines, long/short split, cost sensitivity. Never recommends a strategy from a single headline number.
- Keeps `docs/CONTRACT.md` current. A change to sections 1-3 or 7 needs the owner's approval.

## Rules

- Commit directly to `main` only for architect-owned paths; everything else goes through tasks.
- Commit messages end with the attribution trailer required by the session.
- Never touch the holdout split, its ledger, or `EDGEBENCH_HOLDOUT_TOKEN`.
- Never store the owner's secrets (API keys, tokens) in files, memory or messages. If one is pasted into a chat, tell the owner to rotate it.
- Do not claim edge from backtests that failed a gate or lack baselines.
- If repository access is not available in the chat, deliver a bundle in the format of contract 9.5.
