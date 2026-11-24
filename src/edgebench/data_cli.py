"""``edgebench data ...``: ingest, inspect, verify and split the local price store."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from edgebench.config import ConfigError, load_splits
from edgebench.data import (
    DataError,
    data_version,
    derive_bounds,
    find_gaps,
    merge_ask,
    normalize_m1,
    parse_binance_klines,
    parse_dukascopy_csv,
    verify_store,
    write_m1,
)
from edgebench.data.store import load_manifest, read_raw_m1

RepoRoot = Callable[[], Path]
PARSERS = {"binance": parse_binance_klines, "dukascopy": parse_dukascopy_csv}
DEFAULT_SIDE = {"binance": "trade", "dukascopy": "bid"}


def data_root(repo_root: Path) -> Path:
    """Data folder: ``$EDGEBENCH_DATA`` if set, otherwise ``<repo>/data`` (git-ignored)."""
    override = os.environ.get("EDGEBENCH_DATA")
    return Path(override).resolve() if override else repo_root / "data"


def _read_files(source: str, files: list[str]) -> pd.DataFrame:
    parse = PARSERS[source]
    frames = [parse(Path(name)) for name in files]
    return normalize_m1(pd.concat(frames, ignore_index=True))


def _cmd_ingest(args: argparse.Namespace, repo_root: RepoRoot) -> int:
    root = data_root(repo_root())
    frame = _read_files(args.source, args.files)
    if args.ask_files:
        if args.source != "dukascopy":
            raise DataError("--ask-files is only supported for dukascopy (single-sided candles)")
        frame = merge_ask(frame, _read_files(args.source, args.ask_files))
    side = args.price_side or DEFAULT_SIDE[args.source]
    entries = write_m1(root, args.source, args.symbol, frame, side)
    print(f"{args.source}/{args.symbol}: {len(frame)} M1 bars, price side {side}")
    for entry in entries:
        print(f"  {entry.year}: {entry.rows} rows, {entry.first_ts} .. {entry.last_ts}")
    gaps = find_gaps(frame, args.gap_minutes)
    if gaps.empty:
        print(f"no gaps of {args.gap_minutes}+ minutes")
    else:
        largest = int(gaps["missing_minutes"].max())
        print(f"{len(gaps)} gaps of {args.gap_minutes}+ minutes, largest {largest} minutes")
    return 0


def _datasets(root: Path) -> dict[tuple[str, str], list[dict[str, object]]]:
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for entry in load_manifest(root).values():
        grouped.setdefault((str(entry["source"]), str(entry["symbol"])), []).append(entry)
    return grouped


def _cmd_info(_: argparse.Namespace, repo_root: RepoRoot) -> int:
    root = data_root(repo_root())
    datasets = _datasets(root)
    if not datasets:
        print(f"no data under {root}")
        return 0
    for (source, symbol), entries in sorted(datasets.items()):
        first = min(str(e["first_ts"]) for e in entries)
        last = max(str(e["last_ts"]) for e in entries)
        rows = sum(int(str(e["rows"])) for e in entries)
        sides = sorted({str(e["price_side"]) for e in entries})
        ask = "ask" if any(e["has_ask"] for e in entries) else "no ask"
        print(f"{source}/{symbol}: {rows} rows, {first} .. {last}, side {sides}, {ask}")
    print(f"data_version {data_version(root)[:16]}")
    return 0


def _cmd_verify(_: argparse.Namespace, repo_root: RepoRoot) -> int:
    root = data_root(repo_root())
    problems = verify_store(root)
    for problem in problems:
        print(f"problem: {problem}")
    print("store verified" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def _cmd_gaps(args: argparse.Namespace, repo_root: RepoRoot) -> int:
    frame = read_raw_m1(data_root(repo_root()), args.source, args.symbol)
    gaps = find_gaps(frame, args.min_minutes)
    print(f"{len(gaps)} gaps of {args.min_minutes}+ minutes in {len(frame)} bars")
    largest = gaps.sort_values("missing_minutes", ascending=False).head(args.top)
    for row in largest.itertuples(index=False):
        print(f"  {row.start} .. {row.end}  ({row.missing_minutes} min)")
    return 0


def _cmd_split(args: argparse.Namespace, repo_root: RepoRoot) -> int:
    root, repo = data_root(repo_root()), repo_root()
    datasets = _datasets(root)
    if not datasets:
        raise DataError(f"no data under {root}; ingest data first")
    entries = [e for group in datasets.values() for e in group]
    first = min(pd.Timestamp(str(e["first_ts"])) for e in entries)
    last_end = max(pd.Timestamp(str(e["last_ts"])) for e in entries) + pd.Timedelta(minutes=1)
    path = repo / "config" / "splits.yaml"
    cfg = load_splits(path)
    bounds = derive_bounds(first.to_pydatetime(), last_end.to_pydatetime(), cfg)
    kind = "derived" if bounds.derived else "frozen in config"
    print(f"horizon  {first} .. {last_end}")
    print(f"dev      {bounds.dev_start.date()} .. {bounds.dev_end.date()} (exclusive)")
    print(f"embargo  {bounds.embargo_days} days")
    print(f"holdout  from {bounds.holdout_start.date()} ({kind})")
    if not args.write:
        return 0
    if not bounds.derived:
        raise DataError("holdout_start is already frozen in config/splits.yaml; not overwriting")
    header = (
        f"# Frozen on {datetime.now(UTC).date()} from data {first.date()} .. {last_end.date()}.\n"
        "# Do not change holdout_start after looking at holdout results "
        "(docs/CONTRACT.md 7.1-7.2).\n"
    )
    body = yaml.safe_dump(
        {
            "holdout_fraction": cfg.holdout_fraction,
            "embargo_days": cfg.embargo_days,
            "walk_forward_folds": cfg.walk_forward_folds,
            "dev_start": bounds.dev_start.date(),
            "dev_end": bounds.dev_end.date(),
            "holdout_start": bounds.holdout_start.date(),
        },
        sort_keys=False,
    )
    path.write_text(header + body, encoding="utf-8")
    print(f"written {path}; commit it so the boundary stays fixed")
    return 0


def register(sub: argparse._SubParsersAction[argparse.ArgumentParser], repo_root: RepoRoot) -> None:
    """Add the ``data`` command group to the main parser."""
    data = sub.add_parser("data", help="local price store")
    commands = data.add_subparsers(dest="data_command", required=True)

    def bind(
        parser: argparse.ArgumentParser, func: Callable[[argparse.Namespace, RepoRoot], int]
    ) -> None:
        def run(args: argparse.Namespace) -> int:
            try:
                return func(args, repo_root)
            except (DataError, ConfigError, OSError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

        parser.set_defaults(func=run)

    ingest = commands.add_parser("ingest", help="parse raw files into the store")
    ingest.add_argument("--source", choices=sorted(PARSERS), required=True)
    ingest.add_argument("--symbol", required=True, help="name used in the store, e.g. BTCUSDT")
    ingest.add_argument("--price-side", choices=["bid", "ask", "mid", "trade"])
    ingest.add_argument("--files", nargs="+", required=True, help="raw CSV or zip files")
    ingest.add_argument("--ask-files", nargs="+", help="dukascopy ask candles to merge")
    ingest.add_argument("--gap-minutes", type=int, default=5, help="report gaps of this size")
    bind(ingest, _cmd_ingest)

    bind(commands.add_parser("info", help="list stored datasets"), _cmd_info)
    bind(commands.add_parser("verify", help="check hashes against the manifest"), _cmd_verify)

    gaps = commands.add_parser("gaps", help="list the largest gaps of a dataset")
    gaps.add_argument("--source", choices=sorted(PARSERS), required=True)
    gaps.add_argument("--symbol", required=True)
    gaps.add_argument("--min-minutes", type=int, default=5)
    gaps.add_argument("--top", type=int, default=10)
    bind(gaps, _cmd_gaps)

    split = commands.add_parser("split", help="show or freeze the dev/holdout boundary")
    split.add_argument("--write", action="store_true", help="freeze into config/splits.yaml")
    bind(split, _cmd_split)
