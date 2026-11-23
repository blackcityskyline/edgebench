# Task queue

One file per task: `T-NNN-slug.md` (three or more digits). The runner ignores every other file in this folder.

```yaml
---
id: T-007
title: Implement FVG detector
status: pending                 # pending | blocked | done (architect-owned desired state)
agent: flash-text               # flash-text | flash-vision
depends_on: [T-003]
allowed_paths: [src/edgebench/zones/fvg.py, tests/zones/]   # a trailing / means a directory
context_files: [docs/CONTRACT.md, src/edgebench/contracts/zones.py]
acceptance: ["pytest tests/zones -q", "python -m edgebench.cli gates --quick"]
max_attempts: 3
---
Free-form description: what to build, which contract sections apply, edge cases to cover.
```

Rules: `allowed_paths` is an allowlist and the protected paths are a denylist that always wins. Only the runner changes `status`, never a worker. See `docs/CONTRACT.md` section 9.

Commands: `edgebench tasks` lists the queue, `edgebench loop --dry-run` shows the next runnable task.
