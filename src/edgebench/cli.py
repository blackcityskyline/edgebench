"""Command line entry point: ``edgebench gates | loop | tasks | config-check``."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from edgebench.config import ConfigError, load_all, unconfirmed_items
from edgebench.runner.loop import run_loop
from edgebench.runner.tasks import TaskError, load_tasks


def repo_root() -> Path:
    override = os.environ.get("EDGEBENCH_ROOT")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]


def _cmd_gates(args: argparse.Namespace) -> int:
    script = repo_root() / "gates" / "run.py"
    cmd = [sys.executable, str(script)]
    if args.quick:
        cmd.append("--quick")
    if args.only:
        cmd += ["--only", args.only]
    return subprocess.call(cmd, cwd=repo_root())


def _cmd_loop(args: argparse.Namespace) -> int:
    try:
        for line in run_loop(repo_root() / "tasks", dry_run=args.dry_run):
            print(line)
    except (TaskError, NotImplementedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_tasks(_: argparse.Namespace) -> int:
    try:
        tasks = load_tasks(repo_root() / "tasks")
    except TaskError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for task in tasks:
        print(f"{task.id}  {task.status:<8} {task.agent:<13} {task.title}")
    if not tasks:
        print("no tasks")
    return 0


def _cmd_config_check(_: argparse.Namespace) -> int:
    try:
        config = load_all(repo_root() / "config")
    except (ConfigError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for name, strategy in config.strategies.items():
        print(f"{name}: ok, hash {strategy.config_hash()[:12]}")
    for item in unconfirmed_items(config):
        print(f"warning: {item}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edgebench")
    sub = parser.add_subparsers(dest="command", required=True)

    gates = sub.add_parser("gates", help="run quality gates")
    gates.add_argument("--quick", action="store_true", help="skip slow gates")
    gates.add_argument("--only", help="comma-separated gate ids, e.g. G1,G3")
    gates.set_defaults(func=_cmd_gates)

    loop = sub.add_parser("loop", help="task runner (dry run only until milestone M7)")
    loop.add_argument("--dry-run", action="store_true", help="describe the queue, run nothing")
    loop.set_defaults(func=_cmd_loop)

    tasks = sub.add_parser("tasks", help="list the task queue")
    tasks.set_defaults(func=_cmd_tasks)

    check = sub.add_parser("config-check", help="validate config/ and list placeholders")
    check.set_defaults(func=_cmd_config_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
