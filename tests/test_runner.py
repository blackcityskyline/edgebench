from pathlib import Path

import pytest

from edgebench.runner import (
    PROTECTED_PATHS,
    TaskError,
    is_protected,
    load_tasks,
    next_task,
    parse_task,
    violations,
)
from edgebench.runner.loop import describe_plan, run_loop

TASK_TEXT = """---
id: T-007
title: Implement FVG detector
status: pending
agent: flash-text
depends_on: [T-003]
allowed_paths: [src/edgebench/zones/fvg.py, tests/zones/]
acceptance: ["pytest tests/zones -q"]
---
Implement the detector described in docs/CONTRACT.md section 4.3.
"""


def make_task(task_id: str, status: str = "pending", deps: str = "[]") -> str:
    return (
        f"---\nid: {task_id}\ntitle: t {task_id}\nstatus: {status}\n"
        f"depends_on: {deps}\nallowed_paths: [src/x.py]\n---\nbody\n"
    )


def test_parse_task() -> None:
    task = parse_task(TASK_TEXT)
    assert task.id == "T-007"
    assert task.depends_on == ["T-003"]
    assert task.max_attempts == 3
    assert task.body.startswith("Implement")


@pytest.mark.parametrize(
    "text",
    [
        "no front matter",
        "---\nid: T-001\n",
        "---\n- a list\n---\n",
        "---\nid: bad\ntitle: x\nallowed_paths: [a]\n---\n",
    ],
)
def test_malformed_tasks_are_rejected(text: str) -> None:
    with pytest.raises((TaskError, ValueError)):
        parse_task(text)


def test_next_task_respects_dependencies_and_status(tmp_path: Path) -> None:
    (tmp_path / "T-001-a.md").write_text(make_task("T-001", status="done"))
    (tmp_path / "T-002-b.md").write_text(make_task("T-002", deps="[T-003]"))
    (tmp_path / "T-003-c.md").write_text(make_task("T-003", deps="[T-001]"))
    (tmp_path / "T-004-d.md").write_text(make_task("T-004", status="blocked"))
    (tmp_path / "README.md").write_text("not a task")
    tasks = load_tasks(tmp_path)
    assert [t.id for t in tasks] == ["T-001", "T-002", "T-003", "T-004"]
    chosen = next_task(tasks)
    assert chosen is not None and chosen.id == "T-003"


def test_unknown_dependency_and_name_mismatch(tmp_path: Path) -> None:
    (tmp_path / "T-001-a.md").write_text(make_task("T-001", deps="[T-009]"))
    with pytest.raises(TaskError, match="unknown dependencies"):
        load_tasks(tmp_path)
    (tmp_path / "T-001-a.md").unlink()
    (tmp_path / "T-002-a.md").write_text(make_task("T-001"))
    with pytest.raises(TaskError, match="file name"):
        load_tasks(tmp_path)


def test_protected_paths() -> None:
    for path in (
        "gates/run.py",
        "docs/CONTRACT.md",
        "tasks/T-001-a.md",
        "tests/fixtures/a.json",
        "src/edgebench/contracts/bars.py",
        "AGENTS.md",
        ".github/workflows/ci.yml",
        "tests/test_causality.py",
    ):
        assert is_protected(path), path
    for path in (
        "src/edgebench/zones/fvg.py",
        "tests/zones/test_fvg.py",
        "reports/a.md",
        "README.md",
    ):
        assert not is_protected(path), path
    assert "gates/" in PROTECTED_PATHS


def test_violations_protected_wins_over_allowed() -> None:
    task = parse_task(TASK_TEXT)
    ok = violations(["src/edgebench/zones/fvg.py", "tests/zones/test_fvg.py"], task)
    assert ok == []
    bad = violations(
        ["src/edgebench/zones/other.py", "gates/run.py", "../escape.py", "/etc/passwd"], task
    )
    reasons = {v.path: v.reason for v in bad}
    assert "not in allowed_paths" in reasons["src/edgebench/zones/other.py"]
    assert reasons["gates/run.py"] == "protected path"
    assert len(bad) == 4
    permissive = parse_task(TASK_TEXT.replace("tests/zones/]", "gates/]"))
    assert [v.reason for v in violations(["gates/run.py"], permissive)] == ["protected path"]


def test_loop_is_dry_run_only(tmp_path: Path) -> None:
    assert describe_plan(tmp_path) == ["queue is empty (no T-*.md files in tasks/)"]
    (tmp_path / "T-001-a.md").write_text(make_task("T-001"))
    lines = run_loop(tmp_path, dry_run=True)
    assert lines[-1].startswith("next: T-001")
    with pytest.raises(NotImplementedError):
        run_loop(tmp_path, dry_run=False)
