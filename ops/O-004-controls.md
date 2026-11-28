# O-004: controls (mirror baseline, optimistic bound)

Goal: find out whether the small gross edge of the pattern-free `baseline` (about +0.05R at 2R, rising
with the target) comes from the zones or from the data and the engine. Two controls:

- `mirror`: the baseline's random bars traded in the opposite direction. The report section
  "Zone effect vs artifact" splits the result: zone effect = (baseline - mirror) / 2, artifact =
  (baseline + mirror) / 2 (near zero at cost x0 if the engine and data are neutral).
- `strategy_v1_optimistic`: the same strategy, but a bar that reaches a target and the stop counts
  the target. Together with `strategy_v1` (stop first) it brackets the bar-level ambiguity.

```bash
. .venv/bin/activate
nohup edgebench ops controls > ops/.last.log 2>&1 &
```

Poll with `edgebench ops status O-004`. Expect 30 to 60 minutes. Steps: `gates`, `data_verify`,
`data_info`, `spreads`, `cost0`, `cost1`, `cost2` (strategy_v1 with the mirror trigger), `opt0`, `opt1`
(strategy_v1_optimistic), each run committed. `REPORT.md` links `cost-study.md` (E[R] by cost level and
by target 1R to 15R, by cost-in-R bucket) and `cost-study-optimistic.md`.

If a step fails, escalate as in O-001 (`ops/O-001-first-run.md`). Do not fix anything.

Done means `ops/STATUS.md` shows `O-004 | done` and `reports/ops/O-004/REPORT.md` is on `main`.
