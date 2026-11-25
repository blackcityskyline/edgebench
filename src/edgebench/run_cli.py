"""``edgebench run`` and ``edgebench report``: run a strategy on stored data (contract 7)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from edgebench.config import ConfigError, load_all, unconfirmed_items
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import make_run_id
from edgebench.data.errors import DataError
from edgebench.data.holdout import HoldoutDenied
from edgebench.data.loader import HoldoutRequest, iter_bars, load_m1
from edgebench.data.splits import SplitBounds, derive_bounds
from edgebench.data.store import data_version, load_manifest
from edgebench.data_cli import data_root
from edgebench.engine import run_engine
from edgebench.execution import CostModel
from edgebench.report import RunMeta, build_report
from edgebench.results import candidate_frame, event_frame

RepoRoot = Callable[[], Path]


def code_commit(repo: Path) -> str:
    def git(*args: str) -> str:
        proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else ""

    head = git("rev-parse", "--short", "HEAD") or "unknown"
    return head + ("-dirty" if git("status", "--porcelain") else "")


def _bounds(root: Path, cfg_splits: object) -> SplitBounds:
    entries = list(load_manifest(root).values())
    if not entries:
        raise DataError(f"no data under {root}; ingest data first")
    first = min(pd.Timestamp(str(e["first_ts"])) for e in entries)
    last_end = max(pd.Timestamp(str(e["last_ts"])) for e in entries) + pd.Timedelta(minutes=1)
    return derive_bounds(first.to_pydatetime(), last_end.to_pydatetime(), cfg_splits)  # type: ignore[arg-type]


def _ledger_trials(ledger: Path, config_hash: str) -> int:
    seen = {config_hash}
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            if line:
                rec = json.loads(line)
                if rec.get("split") == "dev":
                    seen.add(rec["config_hash"])
    return len(seen)


def _cmd_run(args: argparse.Namespace, repo_root: RepoRoot) -> int:
    repo = repo_root()
    config = load_all(repo / "config")
    if args.strategy not in config.strategies:
        raise ConfigError(f"unknown strategy {args.strategy!r}; have {sorted(config.strategies)}")
    strategy: StrategyConfig = config.strategies[args.strategy]
    root = data_root(repo)
    instruments = args.instruments.split(",") if args.instruments else strategy.instruments
    unknown = set(instruments) - set(strategy.instruments)
    if unknown:
        raise ConfigError(f"instruments not in the strategy: {sorted(unknown)}")
    bounds = _bounds(root, config.splits)
    warnings = [w for w in unconfirmed_items(config)]
    if bounds.derived:
        warnings.append(
            "split is not frozen in config/splits.yaml (run `edgebench data split --write`)"
        )
    commit = code_commit(repo)
    chash = strategy.config_hash()
    dver = data_version(root)
    run_key = f"{chash}|cost={args.cost_mult:g}|{','.join(sorted(instruments))}|{args.split}"
    run_id = make_run_id(run_key, dver, commit)
    holdout = None
    if args.split == "holdout":
        if not args.holdout_reason:
            raise HoldoutDenied("--holdout-reason is required for the holdout split")
        holdout = HoldoutRequest(
            args.holdout_reason, chash, commit, repo / "holdout" / "ledger.jsonl"
        )
    ledger = repo / "runs" / "ledger.jsonl"
    frames: dict[str, pd.DataFrame] = {}
    event_frames: list[pd.DataFrame] = []
    counts: dict[str, dict[str, int]] = {}
    for name in instruments:
        spec = config.instruments.instruments[name]
        mult = args.cost_mult
        costs = CostModel(
            spec.spread * mult,
            spec.slippage_spreads * spec.spread * mult,
            spec.commission_bps * mult,
        )
        if spec.placeholder:
            warnings.append(f"{name}: placeholder costs")
        print(f"{name}: loading {spec.source}/{spec.symbol} ({args.split})", flush=True)
        try:
            frame = load_m1(root, spec.source, spec.symbol, bounds, args.split, holdout)
        except DataError as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            warnings.append(f"{name}: skipped ({exc})")
            continue
        out = run_engine(strategy, name, iter_bars(frame, "M1"), costs, config.sessions)
        frames[name] = candidate_frame(out, name, strategy.exits.ladder_r)
        event_frames.append(event_frame(out, name))
        counts[name] = out.counts
        print(
            f"  events {len(out.events)}, candidates {len(out.candidates)}, "
            f"trades {len(out.trades)}",
            flush=True,
        )
    if not frames:
        raise DataError("no instrument could be run")
    meta = RunMeta(
        run_id, args.strategy, chash, dver, commit, args.split, args.cost_mult, sorted(frames),
        _ledger_trials(ledger, chash), sorted(set(warnings)), counts,
    )  # fmt: skip
    report = build_report(frames, meta, strategy.exits.ladder_r)
    tables = root / "runs" / run_id
    tables.mkdir(parents=True, exist_ok=True)
    pd.concat(frames.values(), ignore_index=True).to_parquet(tables / "candidates.parquet")
    pd.concat(event_frames, ignore_index=True).to_parquet(tables / "events.parquet")
    if args.split == "holdout":
        print(report)  # holdout results are never written where agents read (contract 7.2)
        return 0
    out_dir = repo / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    manifest = {
        "run_id": run_id, "strategy": args.strategy, "config_hash": chash, "data_version": dver,
        "code_commit": commit, "split": args.split, "cost_mult": args.cost_mult,
        "instruments": sorted(frames), "finished": datetime.now(UTC).isoformat(), "counts": counts,
    }  # fmt: skip
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    keys = ("run_id", "strategy", "config_hash", "data_version", "split", "cost_mult")
    record = {k: manifest[k] for k in (*keys, "instruments", "finished")}
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    print(f"report: {out_dir / 'report.md'}")
    print(f"tables: {tables}")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser], repo_root: RepoRoot) -> None:
    run = sub.add_parser("run", help="run a strategy on stored data and write a report")
    run.add_argument("--strategy", default="strategy_v1")
    run.add_argument("--instruments", help="comma-separated subset of the strategy's instruments")
    run.add_argument("--split", choices=["dev", "holdout"], default="dev")
    run.add_argument(
        "--cost-mult", type=float, default=1.0, help="multiplies spread, slippage, fees"
    )
    run.add_argument("--holdout-reason", help="required for --split holdout")

    def go(args: argparse.Namespace) -> int:
        try:
            return _cmd_run(args, repo_root)
        except (DataError, ConfigError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    run.set_defaults(func=go)
