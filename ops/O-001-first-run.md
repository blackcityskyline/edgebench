# O-001: first run on the real data

Goal: get the first real numbers and a sanity check of the engine on real data, and put everything
the architect needs into `reports/ops/O-001/`. One command does it:

```bash
. .venv/bin/activate
nohup edgebench ops first-run > ops/.last.log 2>&1 &
```

Poll with `edgebench ops status O-001` (prints `running`, `done` or `failed` and the current step).
Expect 20 to 90 minutes for the full run depending on the machine; the pipeline is resumable.

## What the pipeline does (you do not do these by hand)

1. `gates` quick checks. Failure here stops everything: the checkout is broken.
2. `data_info`, `data_verify`: what data exists and that its hashes match. Failure stops.
3. `split` shows the dev/holdout boundary; `split_freeze` writes `config/splits.yaml` once if it is
   still derived. The file is committed. A frozen boundary is never overwritten.
4. `config_check` lists unconfirmed placeholders (informational), `spreads` measures real spreads
   where ask candles exist (informational).
5. `smoke`: the last 30 days of the first available instrument. Failure stops (engine bug on real data).
6. `full`: all instruments of `strategy_v1` that have data in the store, split `dev`. Checkpoint commit.
7. `cost2`: same with spread, slippage and fees doubled. Checkpoint commit.
8. `charts`, `charts_blind`: three sample charts per trigger into `reports/ops/O-001/charts/`.
9. `REPORT.md`, `ops/STATUS.md`, final commit and push.

Instruments that are in the strategy but not in the store (GBPUSD, XAUUSD, US100 at the time of
writing) are skipped without error; the report's funnel shows which ran.

## If it fails

- Step `gates`: someone left the checkout dirty or on an old commit. `git status`, `git pull --rebase
  origin main`, rerun. Still failing: escalate with the output.
- Step `data_verify`: the store does not match its manifest. Do not repair anything. Escalate with
  the listed problems.
- Step `smoke` or `full`: escalate with the traceback from `reports/ops/O-001/outputs/<step>.txt`
  (it is already committed by the final push; if not, paste the last 60 lines into the escalation).
- Out of memory or disk: escalate; do not delete data.
- Push rejected: `git pull --rebase origin main && git push origin HEAD`, once.

## Done means

`ops/STATUS.md` shows `O-001 | done` (or `failed` with the failure reported) and
`reports/ops/O-001/REPORT.md` is on the remote `main`.
