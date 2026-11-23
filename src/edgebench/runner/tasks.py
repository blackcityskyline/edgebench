"""Task files: YAML front matter plus markdown body (docs/CONTRACT.md section 9.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TaskError(ValueError):
    """A task file is malformed or inconsistent."""


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^T-\d{3,}$")
    title: str
    status: Literal["pending", "blocked", "done"] = "pending"
    agent: Literal["flash-text", "flash-vision"] = "flash-text"
    depends_on: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(min_length=1)
    context_files: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    max_attempts: int = Field(3, ge=1, le=10)
    body: str = ""


def parse_task(text: str, source: str = "<task>") -> Task:
    """Parse one task file. The front matter is delimited by lines containing only ``---``."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise TaskError(f"{source}: file must start with a '---' front matter line")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise TaskError(f"{source}: front matter is not closed with '---'") from None
    front = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(front, dict):
        raise TaskError(f"{source}: front matter must be a mapping")
    front["body"] = "\n".join(lines[end + 1 :]).strip()
    return Task.model_validate(front)


def load_tasks(tasks_dir: Path) -> list[Task]:
    """Load ``T-*.md`` files sorted by id. Other files (README.md) are ignored."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for path in sorted(tasks_dir.glob("T-*.md")):
        task = parse_task(path.read_text(encoding="utf-8"), source=path.name)
        if not path.name.startswith(task.id):
            raise TaskError(f"{path.name}: file name must start with the task id {task.id}")
        if task.id in seen:
            raise TaskError(f"duplicate task id {task.id}")
        seen.add(task.id)
        tasks.append(task)
    ids = {t.id for t in tasks}
    for task in tasks:
        missing = [d for d in task.depends_on if d not in ids]
        if missing:
            raise TaskError(f"{task.id}: unknown dependencies {missing}")
    return tasks


def next_task(tasks: list[Task]) -> Task | None:
    """First pending task (by id) whose dependencies are all done."""
    done = {t.id for t in tasks if t.status == "done"}
    for task in sorted(tasks, key=lambda t: t.id):
        if task.status == "pending" and all(dep in done for dep in task.depends_on):
            return task
    return None
