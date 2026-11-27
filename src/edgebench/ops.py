"""Operator pipelines: one command that does a whole checklist and reports into the repository.

``edgebench ops first-run`` runs the first real-data checklist (ops/O-001-first-run.md): checks,
data and split state, spreads, a smoke run, the full run, a cost sensitivity run, sample
charts. Every step's output goes to ``reports/ops/<id>/log.txt``, progress to ``state.json``
(poll it with ``edgebench ops status``), the summary to ``REPORT.md``. Results are committed and
pushed to the repository by the pipeline itself, limited to an allowlist of paths. Steps are
idempotent: a rerun skips finished steps unless ``--force``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from edgebench.config import load_all
from edgebench.data.store import load_manifest
from edgebench.data_cli import data_root
from edgebench.report import build_cost_study

PUSH_ALLOWLIST = ("reports/ops", "runs", "config/splits.yaml", "ops/STATUS.md")
TAIL_LINES = 40
MAX_LOG_LINES = 3000
TRIGGERS = ("sweep", "rejection", "stall", "inside")


@dataclass
class Ctx:
    repo: Path
    out_dir: Path
    outputs: dict[str, str] = field(default_factory=dict)
    python: str = sys.executable

    def cli(self, *args: str) -> list[str]:
        return [self.python, "-m", "edgebench.cli", *args]


@dataclass
class Step:
    name: str
    build: Callable[[Ctx], list[str] | None]  # argv, or None to skip
    required: bool = True  # a failure stops the pipeline
    checkpoint: bool = False  # commit and push after this step


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def available_instruments(repo: Path, strategy: str = "strategy_v1") -> list[str]:
    """Strategy instruments for which the store has data."""
    config = load_all(repo / "config")
    have = {(str(e["source"]), str(e["symbol"])) for e in load_manifest(data_root(repo)).values()}
    return [
        name
        for name in config.strategies[strategy].instruments
        if (
            config.instruments.instruments[name].source,
            config.instruments.instruments[name].symbol,
        )
        in have
    ]


def run_id_from(output: str) -> str | None:
    match = re.search(r"report: .*[/\\]runs[/\\]([0-9a-f]+)[/\\]report\.md", output)
    return match.group(1) if match else None


# -- git ---------------------------------------------------------------------------------------


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def checkpoint(repo: Path, message: str, push: bool = True) -> str:
    """Commit the allowlisted paths and push. Returns a one-line outcome for the log."""
    paths = [p for p in PUSH_ALLOWLIST if (repo / p).exists()]
    if not paths:
        return "nothing to commit"
    git(repo, "add", "--", *paths)
    if git(repo, "diff", "--cached", "--quiet").returncode == 0:
        return "nothing to commit"
    done = git(repo, "commit", "-q", "-m", message)
    if done.returncode != 0:
        return f"commit failed: {done.stderr.strip()[:200]}"
    if not push:
        return "committed (push disabled)"
    pushed = git(repo, "push", "-q", "origin", "HEAD")
    if pushed.returncode != 0:
        git(repo, "pull", "--rebase", "-q", "origin", "main")
        pushed = git(repo, "push", "-q", "origin", "HEAD")
    return "pushed" if pushed.returncode == 0 else f"push failed: {pushed.stderr.strip()[:200]}"


# -- pipeline ----------------------------------------------------------------------------------


def _load_state(path: Path) -> dict[str, object]:
    if path.exists():
        return dict(json.loads(path.read_text(encoding="utf-8")))
    return {"state": "new", "steps": {}}


def _save_state(path: Path, state: dict[str, object]) -> None:
    state["updated"] = now()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def scrub(text: str, repo: Path) -> str:
    """Remove machine-specific paths: the repository becomes ``<repo>``, the home folder ``~``."""
    text = text.replace(str(repo.resolve()), "<repo>").replace(str(repo), "<repo>")
    return text.replace(str(Path.home()), "~")


def _run(argv: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return 127, scrub(f"cannot start {argv[0]}: {exc}", cwd)
    output = proc.stdout + (("\n" + proc.stderr) if proc.stderr else "")
    return proc.returncode, scrub(output, cwd)


def execute(
    steps: list[Step],
    repo: Path,
    out_dir: Path,
    report: Callable[[Ctx, dict[str, object]], str],
    task_id: str,
    force: bool = False,
    push: bool = True,
) -> int:
    ctx = Ctx(repo, out_dir)
    state_path, log_path = out_dir / "state.json", out_dir / "log.txt"
    state = _load_state(state_path)
    steps_state: dict[str, dict[str, object]] = state.setdefault("steps", {})  # type: ignore[assignment]
    state.update(state="running", started=state.get("started", now()))
    status = 0
    for step in steps:
        prior = steps_state.get(step.name)
        outfile = out_dir / "outputs" / f"{step.name}.txt"
        if prior and prior.get("status") in ("ok", "skipped") and not force:
            if outfile.exists():
                ctx.outputs[step.name] = outfile.read_text(encoding="utf-8")
            continue
        state["current"] = step.name
        _save_state(state_path, state)
        argv = step.build(ctx)
        if argv is None:
            steps_state[step.name] = {"status": "skipped", "at": now()}
            continue
        started = time.monotonic()
        code, output = _run(argv, repo)
        seconds = round(time.monotonic() - started, 1)
        ctx.outputs[step.name] = output
        outfile.parent.mkdir(parents=True, exist_ok=True)
        outfile.write_text(output, encoding="utf-8")
        lines = output.splitlines()
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"\n=== {step.name} [{now()}] $ {' '.join(argv)}\n")
            log.write("\n".join(lines[:MAX_LOG_LINES]) + f"\n--- exit {code}, {seconds}s\n")
        steps_state[step.name] = {
            "status": "ok" if code == 0 else "failed",
            "returncode": code,
            "seconds": seconds,
            "at": now(),
        }
        _save_state(state_path, state)
        if step.checkpoint and code == 0:
            steps_state[step.name]["git"] = checkpoint(repo, f"ops {task_id}: {step.name}", push)
        if code != 0 and step.required:
            status = 1
            break
    state["state"] = "failed" if status else "done"
    state.pop("current", None)
    _save_state(state_path, state)
    (out_dir / "REPORT.md").write_text(report(ctx, state), encoding="utf-8")
    write_status(repo, task_id, str(state["state"]))
    final = str(state["state"])
    outcome = checkpoint(repo, f"ops {task_id}: {final}", push)
    print(f"{task_id}: {final}; git: {outcome}")
    return status


def write_status(repo: Path, task_id: str, state: str) -> None:
    path = repo / "ops" / "STATUS.md"
    path.parent.mkdir(exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    head = ["# Ops status", "", "| task | state | updated | report |", "|---|---|---|---|"]
    rows = [ln for ln in lines if ln.startswith("| O-") and not ln.startswith(f"| {task_id} ")]
    rows.append(f"| {task_id} | {state} | {now()} | reports/ops/{task_id}/REPORT.md |")
    path.write_text("\n".join([*head, *sorted(rows)]) + "\n", encoding="utf-8")


# -- shared steps ------------------------------------------------------------------------------


def _run_step(repo: Path, *extra: str) -> Callable[[Ctx], list[str] | None]:
    """A `run` over every strategy instrument that has data; skipped when none has."""
    inst = ",".join(available_instruments(repo))

    def build(ctx: Ctx) -> list[str] | None:
        if not inst:
            return None
        return ctx.cli("run", "--strategy", "strategy_v1", "--instruments", inst, *extra)

    return build


# -- first-run ---------------------------------------------------------------------------------


def first_run_steps(repo: Path) -> list[Step]:
    instruments = available_instruments(repo)
    inst = ",".join(instruments)

    def smoke(ctx: Ctx) -> list[str] | None:
        if not instruments:
            return None
        return ctx.cli("run", "--instruments", instruments[0], "--days", "30")

    def freeze(ctx: Ctx) -> list[str] | None:
        return (
            ctx.cli("data", "split", "--write")
            if "(derived)" in ctx.outputs.get("split", "")
            else None
        )

    def run_args(*extra: str) -> Callable[[Ctx], list[str] | None]:
        def build(ctx: Ctx) -> list[str] | None:
            return (
                ctx.cli("run", "--strategy", "strategy_v1", "--instruments", inst, *extra)
                if inst
                else None
            )

        return build

    def charts(blind: bool) -> Callable[[Ctx], list[str] | None]:
        def build(ctx: Ctx) -> list[str] | None:
            run_id = run_id_from(ctx.outputs.get("full", ""))
            if not run_id:
                return None
            out = ctx.out_dir / "charts" / ("blind" if blind else "context")
            script = (
                "import subprocess, sys\n"
                f"for trig in {list(TRIGGERS)!r}:\n"
                f"    cmd = [sys.executable, '-m', 'edgebench.cli', 'chart', '--run', {run_id!r},\n"
                f"           '--trigger', trig, '--sample', '3', '--out', {str(out)!r}]\n"
                f"    if {blind!r}: cmd.append('--blind')\n"
                "    subprocess.run(cmd, check=False)\n"
            )
            return [ctx.python, "-c", script]

        return build

    return [
        Step("gates", lambda c: c.cli("gates", "--quick")),
        Step("data_info", lambda c: c.cli("data", "info")),
        Step("data_verify", lambda c: c.cli("data", "verify")),
        Step("split", lambda c: c.cli("data", "split")),
        Step("split_freeze", freeze, required=False),
        Step("config_check", lambda c: c.cli("config-check"), required=False),
        Step("spreads", lambda c: c.cli("data", "spreads"), required=False),
        Step("smoke", smoke),
        Step("full", run_args(), checkpoint=True),
        Step("cost2", run_args("--cost-mult", "2"), required=False, checkpoint=True),
        Step("charts", charts(False), required=False),
        Step("charts_blind", charts(True), required=False),
    ]


def _fence(text: str, limit: int = TAIL_LINES) -> str:
    lines = text.strip().splitlines()
    shown = lines if len(lines) <= limit else ["..."] + lines[-limit:]
    return "```\n" + "\n".join(shown) + "\n```"


def first_run_report(ctx: Ctx, state: dict[str, object]) -> str:
    steps: dict[str, dict[str, object]] = state.get("steps", {})  # type: ignore[assignment]
    out = [
        f"# O-001 first real-data run: {state['state']}",
        "",
        f"updated {state.get('updated')}",
        "",
    ]
    out += ["| step | status | seconds |", "|---|---|---|"]
    out += [f"| {n} | {s.get('status')} | {s.get('seconds', '')} |" for n, s in steps.items()]
    for name in (
        "gates",
        "data_info",
        "data_verify",
        "split",
        "split_freeze",
        "config_check",
        "spreads",
    ):
        if name in ctx.outputs:
            out += ["", f"## {name}", "", _fence(ctx.outputs[name])]
    for name, label in (("smoke", "smoke run"), ("full", "full run"), ("cost2", "cost x2 run")):
        if name in ctx.outputs:
            out += ["", f"## {label} (console)", "", _fence(ctx.outputs[name], 15)]
            run_id = run_id_from(ctx.outputs[name])
            src = ctx.repo / "runs" / (run_id or "-") / "report.md"
            if run_id and src.exists() and name != "smoke":
                shutil.copy(src, ctx.out_dir / f"run-{name}.md")
                out += [
                    "",
                    f"Full report: `reports/ops/O-001/run-{name}.md` "
                    f"(also `runs/{run_id}/report.md`).",
                ]
    failed = [n for n, s in steps.items() if s.get("status") == "failed"]
    if failed:
        out += ["", "## Failures", ""]
        for n in failed:
            out += [
                f"### {n} (exit {steps[n].get('returncode')})",
                "",
                _fence(ctx.outputs.get(n, ""), 60),
            ]
    charts = (
        sorted((ctx.out_dir / "charts").rglob("*.png")) if (ctx.out_dir / "charts").exists() else []
    )
    if charts:
        out += ["", f"## Charts ({len(charts)})", ""]
        out += [f"- `{p.relative_to(ctx.repo)}`" for p in charts]
    out += [
        "",
        "Full console log: `reports/ops/O-001/log.txt`.",
        "",
    ]
    return "\n".join(out)


# -- cost study (O-002) -----------------------------------------------------------------------

COST_MULTS = (("cost0", 0.0), ("cost1", 1.0), ("cost2", 2.0))


def cost_study_steps(repo: Path) -> list[Step]:
    steps = [
        Step("gates", lambda c: c.cli("gates", "--quick")),
        Step("data_verify", lambda c: c.cli("data", "verify")),
        Step("spreads", lambda c: c.cli("data", "spreads"), required=False),
    ]
    for name, mult in COST_MULTS:
        steps.append(Step(name, _run_step(repo, "--cost-mult", f"{mult:g}"), checkpoint=True))
    return steps


def cost_study_report(ctx: Ctx, state: dict[str, object]) -> str:
    steps: dict[str, dict[str, object]] = state.get("steps", {})  # type: ignore[assignment]
    out = [f"# O-002 cost study: {state['state']}", "", f"updated {state.get('updated')}", ""]
    out += ["| step | status | seconds |", "|---|---|---|"]
    out += [f"| {n} | {s.get('status')} | {s.get('seconds', '')} |" for n, s in steps.items()]
    frames: dict[float, pd.DataFrame] = {}
    root = data_root(ctx.repo)
    for name, mult in COST_MULTS:
        run_id = run_id_from(ctx.outputs.get(name, ""))
        path = root / "runs" / (run_id or "-") / "candidates.parquet"
        if run_id and path.exists():
            frames[mult] = pd.read_parquet(path)
            src = ctx.repo / "runs" / run_id / "report.md"
            if src.exists():
                shutil.copy(src, ctx.out_dir / f"run-{name}.md")
            out.append(f"\n`{name}`: run `{run_id}`, report `reports/ops/O-002/run-{name}.md`")
    if len(frames) == len(COST_MULTS):
        text = build_cost_study(frames)
        (ctx.out_dir / "cost-study.md").write_text(text, encoding="utf-8")
        out += ["", "Cost study table: `reports/ops/O-002/cost-study.md`", "", text]
    else:
        out += ["", "Cost study not built: not all three runs finished."]
    failed = [n for n, s in steps.items() if s.get("status") == "failed"]
    if failed:
        out += ["", "## Failures", ""]
        for n in failed:
            out += [f"### {n}", "", _fence(ctx.outputs.get(n, ""), 60)]
    out += ["", "Full console log: `reports/ops/O-002/log.txt`.", ""]
    return "\n".join(out)


def cmd_cost_study(args: argparse.Namespace, repo: Path) -> int:
    return execute(
        cost_study_steps(repo),
        repo,
        repo / "reports" / "ops" / "O-002",
        cost_study_report,
        "O-002",
        args.force,
        not args.no_push,
    )


def _repo_root_default() -> Path:
    return Path.cwd()


def cmd_first_run(args: argparse.Namespace, repo: Path) -> int:
    out_dir = repo / "reports" / "ops" / "O-001"
    return execute(
        first_run_steps(repo),
        repo,
        out_dir,
        first_run_report,
        "O-001",
        args.force,
        not args.no_push,
    )


def cmd_status(args: argparse.Namespace, repo: Path) -> int:
    path = repo / "reports" / "ops" / args.task / "state.json"
    if not path.exists():
        print(f"{args.task}: not started")
        return 0
    state = json.loads(path.read_text(encoding="utf-8"))
    print(
        f"{args.task}: {state.get('state')} (current: {state.get('current', '-')}, "
        f"updated {state.get('updated')})"
    )
    for name, step in state.get("steps", {}).items():
        print(f"  {name}: {step.get('status')} {step.get('seconds', '')}s")
    return 0 if state.get("state") in ("running", "done") else 1


def register(
    sub: argparse._SubParsersAction[argparse.ArgumentParser], repo_root: Callable[[], Path]
) -> None:
    ops = sub.add_parser("ops", help="operator pipelines that report into the repository")
    commands = ops.add_subparsers(dest="ops_command", required=True)
    first = commands.add_parser("first-run", help="O-001: first real-data checklist")
    first.add_argument("--force", action="store_true", help="redo finished steps")
    first.add_argument("--no-push", action="store_true", help="commit but do not push")
    first.set_defaults(func=lambda a: cmd_first_run(a, repo_root()))
    cost = commands.add_parser("cost-study", help="O-002: gross / net / x2 cost comparison")
    cost.add_argument("--force", action="store_true", help="redo finished steps")
    cost.add_argument("--no-push", action="store_true", help="commit but do not push")
    cost.set_defaults(func=lambda a: cmd_cost_study(a, repo_root()))
    status = commands.add_parser("status", help="progress of a running pipeline")
    status.add_argument("task", nargs="?", default="O-001")
    status.set_defaults(func=lambda a: cmd_status(a, repo_root()))
