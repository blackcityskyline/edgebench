# Running a backtest

Prerequisites: data ingested (`docs/DATA.md`), split frozen (`edgebench data split --write`, commit `config/splits.yaml`).

```bash
edgebench config-check                       # lists placeholders you have not confirmed
edgebench run --strategy strategy_v1 --instruments EURUSD,BTCUSDT
edgebench run --strategy strategy_v1 --cost-mult 2     # cost sensitivity: spread, slippage and fees x2
```

Output:

- `runs/<run_id>/report.md` and `manifest.json` (small, commit them so the architect can read them);
  `runs/ledger.jsonl` records every run and gives the "trials so far" counter.
- `data/runs/<run_id>/candidates.parquet` and `events.parquet` (git-ignored): one row per candidate
  and per touch episode, for any analysis you want to do in pandas.

How to read the report: each row is a group of candidate trades; `E[R] @kR` is the average net result
of the policy "target at kR, stop at the stop, timeout after `max_hold_minutes`", with a 95% interval
from resampling whole days. The `baseline` trigger is a random bar inside the same zone episodes with
the same stop rule; **"Trigger minus baseline"** is the part of the result that a pattern adds over just
being at the zone. `*` marks an interval that excludes zero. With dozens of cells on a page some stars
appear by chance, and the more strategy variants were tried (`trials so far`), the less one star means.

Holdout: `--split holdout --holdout-reason "..."` with `EDGEBENCH_HOLDOUT_TOKEN` set in your own shell.
The result is printed only and is never written to `runs/` (contract 7.2). Use it once per finished idea.

Current limits: only the `market_next_open` entry policy; fixed spread per instrument from
`config/instruments.yaml` (placeholders) even where ask candles exist; sessions apply to all instruments.
