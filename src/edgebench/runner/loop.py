"""Runner skeleton. Worker execution is added together with the research loop (milestone M7).

For now the runner can only describe what it would do, so the task format and the protected-path
rules can be exercised and reviewed before any agent is started.
"""

from __future__ import annotations

from pathlib import Path

from edgebench.runner.tasks import Task, load_tasks, next_task


def describe_plan(tasks_dir: Path) -> list[str]:
    """Lines describing the queue and the next task the loop would run."""
    tasks = load_tasks(tasks_dir)
    if not tasks:
        return ["queue is empty (no T-*.md files in tasks/)"]
    lines = [f"{t.id}  {t.status:<8} {t.agent:<13} {t.title}" for t in tasks]
    upcoming = next_task(tasks)
    if upcoming is None:
        lines.append("no runnable task: everything is done, blocked or waiting for dependencies")
    else:
        lines.append(f"next: {upcoming.id} ({upcoming.title})")
    return lines


def run_loop(tasks_dir: Path, dry_run: bool = True) -> list[str]:
    if not dry_run:
        raise NotImplementedError("worker execution is added in milestone M7; use --dry-run")
    return describe_plan(tasks_dir)


def runnable(tasks: list[Task]) -> Task | None:
    """Alias kept for the future loop implementation."""
    return next_task(tasks)
