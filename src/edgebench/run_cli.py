"""``edgebench run`` and ``edgebench report``: run a strategy on stored data (contract 7)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from edgebench.chart import AFTER, BEFORE, render_candidate, visible_bars
from edgebench.config import ConfigError, load_all, unconfirmed_items
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import make_run_id
from edgebench.data.errors import DataError
from edgebench.data.holdout import HoldoutDenied
from edgebench.data.loader import HoldoutRequest, iter_bars, load_m1
from edgebench.data.splits import SplitBounds, derive_bounds
from edgebench.data.store import data_version, load_manifest, read_raw_m1
from edgebench.data_cli import data_root
from edgebench.engine import run_engine
from edgebench.execution import CostModel
from edgebench.report import RunMeta, build_report
from edgebench.results import candidate_frame, event_frame, observation_frame

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


@dataclass
class _Job:
    repo: Path
    strategy: str
    instrument: str
    split: Literal["dev", "holdout"]
    bounds: SplitBounds
    mult: float
    days: int | None
    holdout: HoldoutRequest | None


@dataclass
class _Result:
    instrument: str
    message: str
    warning: str | None = None
    candidates: pd.DataFrame | None = None
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    observations: pd.DataFrame = field(default_factory=pd.DataFrame)
    counts: dict[str, int] = field(default_factory=dict)


def _run_instrument(job: _Job) -> _Result:
    """One instrument end to end. Top level so it can run in a worker process."""
    config = load_all(job.repo / "config")
    strategy = config.strategies[job.strategy]
    spec = config.instruments.instruments[job.instrument]
    costs = CostModel.from_spec(spec, job.mult)
    root = data_root(job.repo)
    head = f"{job.instrument}: {spec.source}/{spec.symbol} ({job.split})"
    try:
        frame = load_m1(root, spec.source, spec.symbol, job.bounds, job.split, job.holdout)
    except HoldoutDenied:
        raise  # a denied holdout is an error for the whole run, never a quiet skip
    except DataError as exc:
        return _Result(
            job.instrument, f"{head}: skipped ({exc})", f"{job.instrument}: skipped ({exc})"
        )
    if job.days:
        cut = frame["ts_open"].iloc[-1] - pd.Timedelta(days=job.days)
        frame = frame[frame["ts_open"] >= cut].reset_index(drop=True)
    out = run_engine(strategy, job.instrument, iter_bars(frame, "M1"), costs, config.sessions)
    message = (
        f"{head}: events {len(out.events)}, candidates {len(out.candidates)}, "
        f"trades {len(out.trades)}"
    )
    warning = f"{job.instrument}: placeholder costs" if spec.placeholder else None
    return _Result(
        job.instrument,
        message,
        warning,
        candidate_frame(
            out,
            job.instrument,
            strategy.exits.ladder_r,
            strategy.exits.be_triggers_r,
            strategy.exits.ambiguity == "target_first",
        ),
        event_frame(out, job.instrument),
        observation_frame(out, job.instrument),
        out.counts,
    )


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
    if args.days:
        warnings.append(f"smoke test: only the last {args.days} days of each dataset")
    commit = code_commit(repo)
    chash = strategy.config_hash()
    dver = data_version(root)
    run_key = (
        f"{chash}|cost={args.cost_mult:g}|{','.join(sorted(instruments))}|{args.split}|"
        f"days={args.days or 'all'}"
    )
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
    obs_frames: list[pd.DataFrame] = []
    counts: dict[str, dict[str, int]] = {}
    jobs = [
        _Job(repo, args.strategy, name, args.split, bounds, args.cost_mult, args.days, holdout)
        for name in instruments
    ]
    workers = max(1, min(args.jobs, len(jobs)))
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_run_instrument, jobs))
    else:
        results = [_run_instrument(job) for job in jobs]
    for res in results:
        print(res.message, flush=True)
        if res.warning:
            warnings.append(res.warning)
        if res.candidates is None:
            continue
        frames[res.instrument] = res.candidates
        event_frames.append(res.events)
        obs_frames.append(res.observations)
        counts[res.instrument] = res.counts
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
    pd.concat(obs_frames, ignore_index=True).to_parquet(tables / "observations.parquet")
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


def _find_run(root: Path, prefix: str) -> Path:
    runs = root / "runs"
    found = sorted(p for p in runs.iterdir() if p.name.startswith(prefix)) if runs.is_dir() else []
    if len(found) != 1:
        raise DataError(f"run {prefix!r}: {len(found)} matches under {runs}")
    return found[0]


def _cmd_chart(args: argparse.Namespace, repo_root: RepoRoot) -> int:
    repo = repo_root()
    root = data_root(repo)
    config = load_all(repo / "config")
    run_dir = _find_run(root, args.run)
    cands = pd.read_parquet(run_dir / "candidates.parquet")
    obs = pd.read_parquet(run_dir / "observations.parquet")
    if args.candidate:
        cands = cands[cands["candidate_id"] == args.candidate]
    if args.instrument:
        cands = cands[cands["instrument"] == args.instrument]
    if args.trigger:
        cands = cands[cands["trigger"] == args.trigger]
    if args.side:
        cands = cands[cands["side"] == args.side.upper()]
    if cands.empty:
        raise DataError("no candidates match the filters")
    if not args.candidate and len(cands) > args.sample:
        cands = cands.sample(n=args.sample, random_state=args.seed)
    out_dir = Path(args.out) if args.out else root / "charts" / run_dir.name
    for _, cand in cands.sort_values("ts_decision").iterrows():
        spec = config.instruments.instruments[cand["instrument"]]
        touch = pd.Timestamp(cand["touch_start"])
        decision = pd.Timestamp(cand["ts_decision"])
        m1 = read_raw_m1(
            root, spec.source, spec.symbol, touch - BEFORE - pd.Timedelta(days=1), decision + AFTER
        )
        bars = visible_bars(m1, touch, decision, args.blind)
        mine = obs[obs["event_id"] == cand["event_id"]]
        safe = str(cand["candidate_id"]).replace(":", "_").replace("#", "-")
        path = render_candidate(bars, cand, mine, out_dir / f"{safe}.png", blind=args.blind)
        print(path)
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
    run.add_argument("--days", type=int, help="smoke test: only the last N days of each dataset")
    run.add_argument(
        "--jobs", type=int, default=min(4, os.cpu_count() or 1), help="instruments in parallel"
    )

    def go(args: argparse.Namespace) -> int:
        try:
            return _cmd_run(args, repo_root)
        except (DataError, ConfigError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    run.set_defaults(func=go)

    chart = sub.add_parser("chart", help="draw candidates of a run (needs matplotlib)")
    chart.add_argument("--run", required=True, help="run id or unique prefix")
    chart.add_argument("--candidate", help="one candidate id")
    chart.add_argument("--instrument")
    chart.add_argument("--trigger")
    chart.add_argument("--side", choices=["long", "short", "LONG", "SHORT"])
    chart.add_argument("--sample", type=int, default=6, help="random candidates to draw")
    chart.add_argument("--seed", type=int, default=0)
    chart.add_argument("--blind", action="store_true", help="only what was known at the decision")
    chart.add_argument("--out", help="output folder (default data/charts/<run>)")

    def draw(args: argparse.Namespace) -> int:
        try:
            return _cmd_chart(args, repo_root)
        except (DataError, ConfigError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    chart.set_defaults(func=draw)
