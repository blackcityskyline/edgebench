"""Protected paths and the allowed-path check for worker branches (docs/CONTRACT.md 9.4).

Protected paths are a denylist that wins over a task's ``allowed_paths``.
A pattern ending in ``/`` is a directory prefix; any other pattern is an exact path.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from edgebench.runner.tasks import Task

PROTECTED_PATHS: tuple[str, ...] = (
    "gates/",
    "tests/fixtures/",
    "tests/test_causality.py",
    "tests/test_determinism.py",
    "docs/",
    "tasks/",
    "hypotheses/",
    "src/edgebench/contracts/",
    "src/edgebench/runner/",
    "holdout/",
    ".github/",
    "AGENTS.md",
    "ARCHITECT.md",
)


@dataclass(frozen=True)
class Violation:
    path: str
    reason: str


def normalize(path: str) -> str | None:
    """Return a clean repo-relative POSIX path, or None if it escapes the repository."""
    candidate = PurePosixPath(path.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    parts = [p for p in candidate.parts if p != "."]
    return "/".join(parts) if parts else None


def matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern


def is_protected(path: str) -> bool:
    return any(matches(path, pattern) for pattern in PROTECTED_PATHS)


def violations(changed: Iterable[str], task: Task | None = None) -> list[Violation]:
    """Paths a worker may not have changed: protected ones, and those outside ``allowed_paths``."""
    found: list[Violation] = []
    for raw in changed:
        path = normalize(raw)
        if path is None:
            found.append(Violation(raw, "path escapes the repository"))
        elif is_protected(path):
            found.append(Violation(path, "protected path"))
        elif task is not None and not any(matches(path, p) for p in task.allowed_paths):
            found.append(Violation(path, f"not in allowed_paths of {task.id}"))
    return found
