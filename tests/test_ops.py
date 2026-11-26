"""The ops pipeline: logging, state, resumability, failure handling and the git allowlist."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from edgebench.data.store import write_m1
from edgebench.data.synthetic import make_m1
from edgebench.ops import (
    Ctx,
    Step,
    available_instruments,
    checkpoint,
    execute,
    run_id_from,
    scrub,
    write_status,
)

ROOT = Path(__file__).resolve().parents[1]


def sh(cwd: Path, *args: str) -> str:
    done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    sh(tmp_path, "git", "clone", "-q", str(remote), str(work))
    sh(work, "git", "config", "user.email", "t@example.com")
    sh(work, "git", "config", "user.name", "t")
    (work / "README.md").write_text("x\n")
    sh(work, "git", "add", "README.md")
    sh(work, "git", "commit", "-q", "-m", "init")
    sh(work, "git", "push", "-q", "origin", "HEAD:main")
    return work


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def report(ctx: Ctx, state: dict[str, object]) -> str:
    return f"state={state['state']} outputs={sorted(ctx.outputs)}\n"


def test_pipeline_logs_reports_and_pushes_only_allowlisted_paths(repo: Path) -> None:
    (repo / "scratch.txt").write_text("not for the repo\n")
    steps = [
        Step("one", lambda c: py("print('hello')")),
        Step("two", lambda c: py("print('world')"), checkpoint=True),
    ]
    out = repo / "reports" / "ops" / "O-009"
    assert execute(steps, repo, out, report, "O-009") == 0
    state = json.loads((out / "state.json").read_text())
    assert state["state"] == "done" and state["steps"]["two"]["git"] == "pushed"
    assert "hello" in (out / "log.txt").read_text()
    assert (out / "REPORT.md").read_text().startswith("state=done")
    assert "| O-009 | done |" in (repo / "ops" / "STATUS.md").read_text()
    tracked = sh(repo, "git", "ls-tree", "-r", "--name-only", "origin/main").split()
    assert "reports/ops/O-009/REPORT.md" in tracked and "scratch.txt" not in tracked
    assert sh(repo, "git", "status", "--porcelain").strip() == "?? scratch.txt"


def test_rerun_skips_finished_steps_and_force_redoes_them(repo: Path) -> None:
    marker = repo / "count.txt"
    code = f"open({str(marker)!r}, 'a').write('x')"
    steps = [Step("count", lambda c: py(code))]
    out = repo / "reports" / "ops" / "O-009"
    execute(steps, repo, out, report, "O-009", push=False)
    execute(steps, repo, out, report, "O-009", push=False)
    assert marker.read_text() == "x"
    execute(steps, repo, out, report, "O-009", force=True, push=False)
    assert marker.read_text() == "xx"


def test_a_required_failure_stops_but_an_optional_one_does_not(repo: Path) -> None:
    out = repo / "reports" / "ops" / "O-009"
    steps = [
        Step("optional", lambda c: py("import sys; print('bad'); sys.exit(3)"), required=False),
        Step("after", lambda c: py("print('ran')")),
        Step("required", lambda c: py("import sys; sys.exit(1)")),
        Step("never", lambda c: py("print('no')")),
    ]
    assert execute(steps, repo, out, report, "O-009", push=False) == 1
    state = json.loads((out / "state.json").read_text())
    assert state["state"] == "failed"
    assert {k: v["status"] for k, v in state["steps"].items()} == {
        "optional": "failed",
        "after": "ok",
        "required": "failed",
    }
    assert "never" not in state["steps"]


def test_steps_can_use_earlier_outputs_and_skip_themselves(repo: Path) -> None:
    out = repo / "reports" / "ops" / "O-009"
    seen: list[str] = []

    def second(ctx: Ctx) -> list[str] | None:
        seen.append(ctx.outputs["first"].strip())
        return None

    steps = [Step("first", lambda c: py("print('token')")), Step("second", second)]
    execute(steps, repo, out, report, "O-009", push=False)
    assert seen == ["token"]
    assert json.loads((out / "state.json").read_text())["steps"]["second"]["status"] == "skipped"


def test_checkpoint_survives_a_diverged_remote(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    sh(tmp_path, "git", "clone", "-q", str(tmp_path / "remote.git"), str(other))
    sh(other, "git", "config", "user.email", "t@example.com")
    sh(other, "git", "config", "user.name", "t")
    (other / "other.txt").write_text("y\n")
    sh(other, "git", "add", "other.txt")
    sh(other, "git", "commit", "-q", "-m", "other")
    sh(other, "git", "push", "-q", "origin", "HEAD:main")
    (repo / "runs").mkdir()
    (repo / "runs" / "a.txt").write_text("z\n")
    assert checkpoint(repo, "ops test") == "pushed"
    assert checkpoint(repo, "ops test again") == "nothing to commit"


def test_status_table_keeps_one_row_per_task(repo: Path) -> None:
    write_status(repo, "O-001", "running")
    write_status(repo, "O-002", "done")
    write_status(repo, "O-001", "done")
    rows = [
        ln for ln in (repo / "ops" / "STATUS.md").read_text().splitlines() if ln.startswith("| O-")
    ]
    assert [r.split("|")[1].strip() for r in rows] == ["O-001", "O-002"] and "done" in rows[0]


def test_run_id_is_parsed_from_the_run_cli_output() -> None:
    text = "EURUSD: loading\nreport: /home/u/edgebench/runs/3fa9c01d2b/report.md\ntables: /x\n"
    assert run_id_from(text) == "3fa9c01d2b" and run_id_from("nothing") is None


def test_available_instruments_follow_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    data = tmp_path / "data"
    monkeypatch.setenv("EDGEBENCH_DATA", str(data))
    assert available_instruments(tmp_path) == []
    write_m1(data, "dukascopy", "eurusd", make_m1(500, seed=1), "bid")
    write_m1(data, "binance", "BTCUSDT", make_m1(500, seed=2), "trade")
    assert available_instruments(tmp_path) == ["EURUSD", "BTCUSDT"]


def test_scrub_hides_the_repository_and_home_paths(tmp_path: Path) -> None:
    home = str(Path.home())
    text = f"report: {tmp_path}/runs/ab12/report.md and {home}/.cache/x"
    clean = scrub(text, tmp_path)
    assert str(tmp_path) not in clean and home not in clean
    assert run_id_from(clean) == "ab12"
