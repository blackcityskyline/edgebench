# RUN_ME: operator instructions

You were told to "read RUN_ME.md and do it". This file is the whole job. Do not ask the owner
questions, do not invent steps, do not improve the code. Follow it literally and report in the repo.

You are in **operator mode**, not worker mode: you run commands and commit their output. You do
**not** edit source code, tests, configs (except what a command itself writes), docs or this file.
If something needs a code change, you stop and write an escalation (below); the architect fixes it.

## 1. Find the work

```bash
cd "$(git rev-parse --show-toplevel)"        # the edgebench checkout
git pull --rebase origin main
cat ops/STATUS.md 2>/dev/null                # which ops tasks are already done
ls ops/O-*.md                                # the list of ops tasks, in order
```

Take the first `O-NNN-*.md` file whose id is **not** `done` in `ops/STATUS.md` (a missing row means
not done). Open it and follow it. Tasks are done in order; O-001 is `ops/O-001-first-run.md`, O-002 is `ops/O-002-cost-study.md`, O-003 is `ops/O-003-expand-and-costs.md`, O-004 is `ops/O-004-controls.md`.

## 2. Environment (once)

```bash
test -d .venv || python3 -m venv .venv
. .venv/bin/activate
pip install -q -e '.[dev]'
```

If `pip` or `python3` fails, go to section 4 with the exact error.

## 3. Do the task and report

The task file gives one command that does everything and commits/pushes its own report. Long
commands (tens of minutes) must run in the background and be polled, because your own tool calls
time out:

```bash
nohup <the command from the task file> > ops/.last.log 2>&1 &
```

Then poll every 60 to 120 seconds with the status command from the task file until it prints
`done` or `failed`. Do not start the command twice. If your shell was restarted and you are unsure
whether it still runs, check `ps aux | grep edgebench` and the status command before starting again.
Rerunning is safe: finished steps are skipped.

When the state is `done` or `failed`:

1. Look at `git status` and `git log -3`. The pipeline already committed and pushed
   `reports/ops/<id>/`, `runs/`, `ops/STATUS.md` and, in O-001, `config/splits.yaml`. If the push
   failed (the report says so), run `git pull --rebase origin main && git push origin HEAD` once.
2. Your final message to the owner is at most 10 lines: the state, the path of the report
   (`reports/ops/<id>/REPORT.md`), and the failed step names if any. Do not interpret results and do
   not give trading opinions: the architect reads the report from the repository.

## 4. If you are stuck

Write `reports/ops/<id>/ESCALATION.md` with: what you ran (exact commands), the exact error text, and
the one question for the architect. Then commit and push **only** that file:

```bash
git add reports/ops && git commit -m "ops <id>: escalation" && git push origin HEAD
```

and stop. Never "fix" a failing gate, test or config yourself, never delete data, never run
`--force` on an ops command unless the task file says so, never set `EDGEBENCH_HOLDOUT_TOKEN`,
never read or request the holdout split, never put keys or tokens into the repository.
