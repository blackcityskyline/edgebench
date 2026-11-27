# O-003: add GBPUSD, XAUUSD, US100 and rerun the cost study on venue costs

Goal: the strategy lists seven instruments but only EURUSD and four crypto pairs are in the store.
`config/instruments.yaml` now holds the owner's real venue costs (fee 0.35 bps forex/XAU/US100,
0.8 bps crypto). This task downloads the three missing Dukascopy instruments, checks their price
scale, and runs the cost study (cost x0, x1, x2 on identical candidates) on all instruments.

```bash
. .venv/bin/activate
nohup edgebench ops expand > ops/.last.log 2>&1 &
```

Poll with `edgebench ops status O-003`. Expect 1 to 2 hours: the download (about 4 years of daily
archives, bid and ask, three instruments) is the slow part and resumes from cache, then about 30
minutes of runs. Instruments already in the store are skipped.

## Steps

`gates`, then per instrument `fetch_<id>` (tools/fetch_dukascopy.py into `data/raw/`, which is not
committed), `ingest_<id>` (bid + ask candles into the store), `pricecheck_<id>` (first, last, min and
max close; fails when the price scale is wrong, e.g. gold or the index off by 1000x), then
`data_verify`, `data_info`, `spreads`, and the three runs `cost0`, `cost1`, `cost2` (each committed).
`REPORT.md` holds the comparison tables (`cost-study.md`) and the three run reports.

## If it fails

- `fetch_*` fails with HTTP errors for many days: the network blocks `datafeed.dukascopy.com`.
  Escalate with the last 30 lines of `reports/ops/O-003/outputs/fetch_<id>.txt`. Do not try other
  download tools or sources.
- `pricecheck_*` fails: the point size of that instrument is wrong. Do not edit anything. Escalate
  with the printed first and last close; the architect fixes `--point`.
- Everything else: as in O-001 (`ops/O-001-first-run.md`). Escalate, do not fix.

Done means `ops/STATUS.md` shows `O-003 | done` and `reports/ops/O-003/REPORT.md` is on `main`.
