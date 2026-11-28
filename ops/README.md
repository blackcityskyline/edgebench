# Operator tasks

Ops tasks are checklists that run on the owner's machine (where the data is) and report into the repo.
They differ from `tasks/` (code written by worker agents under gates): an ops task runs one command of
the project itself and commits the output. The entry point for an agent is `RUN_ME.md`.

| id | what | command |
|---|---|---|
| O-001 | first real-data run: checks, split freeze, spreads, smoke run, full run, cost x2, charts | `edgebench ops first-run` |
| O-002 | cost study: the same candidates at cost x0 (gross), x1, x2 with a comparison table | `edgebench ops cost-study` |
| O-003 | fetch GBPUSD, XAUUSD, US100 with a price-scale check, then the cost study on all instruments with venue costs | `edgebench ops expand` |
| O-004 | controls: mirror baseline (zone effect vs artifact) and the optimistic ambiguity bound, venue costs | `edgebench ops controls` |

`ops/STATUS.md` is written by the pipelines. Reports live in `reports/ops/<id>/`. To add an ops task,
write `ops/O-NNN-slug.md` (protected: only the architect edits `ops/` and `RUN_ME.md`).
