# O-002: cost study (gross vs net vs x2)

Goal: separate "does the entry have any edge before costs" from "do costs eat it". O-001 showed that
friction (spread, stop slippage, commission) is large next to micro-stops, so net numbers alone say
little. This task prices the **same candidates** at three cost levels (the filters use the nominal
spread, so the candidate set does not move):

- `cost0`: no spread, slippage or commission (gross). For the pattern-free `baseline` trigger this
  should be close to zero; a clear deviation points at an engine or data problem.
- `cost1`: nominal costs from `config/instruments.yaml` (some are still placeholders).
- `cost2`: costs doubled.

```bash
. .venv/bin/activate
nohup edgebench ops cost-study > ops/.last.log 2>&1 &
```

Poll with `edgebench ops status O-002`. Expect about 20 to 60 minutes (instruments run in parallel,
`--jobs`). The pipeline is resumable. Steps: `gates`, `data_verify`, `spreads`, `cost0`, `cost1`,
`cost2` (each run is committed), then `REPORT.md` with the comparison table
(`reports/ops/O-002/cost-study.md`) and the three run reports.

Failure handling is the same as in O-001 (see `ops/O-001-first-run.md`): escalate, do not fix.

Done means `ops/STATUS.md` shows `O-002 | done` and `reports/ops/O-002/REPORT.md` is on `main`.
