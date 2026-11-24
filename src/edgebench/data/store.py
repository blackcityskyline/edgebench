"""Parquet store and manifest (docs/CONTRACT.md section 3).

Layout under a data root: ``parquet/{source}/{symbol}/m1/{year}.parquet`` and ``manifest.json``.
The manifest records, per file, the row count, first and last timestamps, the price side, a sha256
of the file bytes and a ``content_sha256`` of the canonical frame contents. ``data_version`` hashes
only content fields, so upgrading pyarrow (which may change file bytes) does not change it.

``read_raw_m1`` ignores the dev/holdout split. Research code must use ``edgebench.data.loader``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from edgebench.data.errors import DataError
from edgebench.data.schema import ASK_COLUMNS, M1_COLUMNS, assert_valid_m1, normalize_m1

LOADER_VERSION = "1"
PRICE_SIDES = ("bid", "ask", "mid", "trade")
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class FileEntry:
    source: str
    symbol: str
    year: int
    price_side: str
    rows: int
    first_ts: str
    last_ts: str
    has_ask: bool
    sha256: str
    content_sha256: str
    loader_version: str


def parquet_path(root: Path, source: str, symbol: str, year: int) -> Path:
    return root / "parquet" / source / symbol / "m1" / f"{year}.parquet"


def content_hash(frame: pd.DataFrame) -> str:
    """Hash of the canonical frame contents (timestamps as int64 ns, floats as float64 bytes)."""
    digest = hashlib.sha256()
    digest.update(pd.DatetimeIndex(frame["ts_open"]).asi8.tobytes())
    for column in [c for c in frame.columns if c != "ts_open"]:
        values = frame[column].to_numpy(dtype="float64")
        digest.update(column.encode())
        digest.update(np.where(np.isnan(values), np.nan, values).tobytes())
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest(root: Path) -> dict[str, dict[str, Any]]:
    path = root / MANIFEST_NAME
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files")
    if not isinstance(files, dict):
        raise DataError(f"{path}: malformed manifest")
    return dict(files)


def save_manifest(root: Path, files: dict[str, dict[str, Any]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    payload = {"manifest_version": 1, "files": dict(sorted(files.items()))}
    (root / MANIFEST_NAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _entry_for(
    path: Path, root: Path, source: str, symbol: str, year: int, side: str, frame: pd.DataFrame
) -> tuple[str, FileEntry]:
    entry = FileEntry(
        source=source,
        symbol=symbol,
        year=year,
        price_side=side,
        rows=len(frame),
        first_ts=frame["ts_open"].iloc[0].isoformat(),
        last_ts=frame["ts_open"].iloc[-1].isoformat(),
        has_ask=all(c in frame.columns and frame[c].notna().any() for c in ASK_COLUMNS),
        sha256=_file_sha256(path),
        content_sha256=content_hash(frame),
        loader_version=LOADER_VERSION,
    )
    return path.relative_to(root).as_posix(), entry


def write_m1(
    root: Path, source: str, symbol: str, frame: pd.DataFrame, price_side: str
) -> list[FileEntry]:
    """Validate ``frame``, merge it into the per-year files and update the manifest.

    Overlapping minutes must be identical to what is already stored; a conflict raises DataError so
    two different versions of the same minute are never silently mixed.
    """
    if price_side not in PRICE_SIDES:
        raise DataError(f"price_side must be one of {PRICE_SIDES}")
    frame = normalize_m1(frame)
    assert_valid_m1(frame)
    manifest = load_manifest(root)
    written: list[FileEntry] = []
    for year, part in frame.groupby(frame["ts_open"].dt.year):
        year = int(year)
        path = parquet_path(root, source, symbol, year)
        if path.exists():
            stored = normalize_m1(pd.read_parquet(path))
            part = normalize_m1(pd.concat([stored, part], ignore_index=True))
        part = part.reset_index(drop=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        part.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
        key, entry = _entry_for(path, root, source, symbol, year, price_side, part)
        manifest[key] = asdict(entry)
        written.append(entry)
    save_manifest(root, manifest)
    return written


def read_raw_m1(
    root: Path,
    source: str,
    symbol: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Read M1 bars with ``start <= ts_open < end``. Ignores the dev/holdout split."""
    folder = root / "parquet" / source / symbol / "m1"
    files = sorted(folder.glob("*.parquet")) if folder.is_dir() else []
    if not files:
        raise DataError(f"no data for {source}/{symbol} under {root}")
    parts: list[pd.DataFrame] = []
    for path in files:
        year = int(path.stem)
        if start is not None and year < start.year:
            continue
        if end is not None and year > end.year:
            continue
        parts.append(pd.read_parquet(path))
    if not parts:
        raise DataError(f"no files for {source}/{symbol} cover the requested range")
    frame = normalize_m1(pd.concat(parts, ignore_index=True))
    if start is not None:
        frame = frame[frame["ts_open"] >= start]
    if end is not None:
        frame = frame[frame["ts_open"] < end]
    return frame.reset_index(drop=True)


def dataset_range(root: Path, source: str, symbol: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last ``ts_open`` of a dataset according to the manifest."""
    entries = [
        e for e in load_manifest(root).values() if e["source"] == source and e["symbol"] == symbol
    ]
    if not entries:
        raise DataError(f"{source}/{symbol} is not in the manifest")
    first = min(pd.Timestamp(e["first_ts"]) for e in entries)
    last = max(pd.Timestamp(e["last_ts"]) for e in entries)
    return first, last


def verify_store(root: Path) -> list[str]:
    """Recompute hashes and counts for every manifest entry; return problems found."""
    problems: list[str] = []
    for key, entry in load_manifest(root).items():
        path = root / key
        if not path.exists():
            problems.append(f"{key}: file is missing")
            continue
        if _file_sha256(path) != entry["sha256"]:
            problems.append(f"{key}: file hash differs from the manifest")
        frame = normalize_m1(pd.read_parquet(path))
        if len(frame) != entry["rows"]:
            problems.append(f"{key}: {len(frame)} rows, manifest says {entry['rows']}")
        if content_hash(frame) != entry["content_sha256"]:
            problems.append(f"{key}: content hash differs from the manifest")
    return problems


def data_version(root: Path, datasets: list[tuple[str, str]] | None = None) -> str:
    """Version of the stored data: sha256 over content fields of the manifest entries.

    ``datasets`` limits the hash to given ``(source, symbol)`` pairs so adding an unrelated
    instrument does not change the version of runs that do not use it.
    """
    wanted = set(datasets) if datasets is not None else None
    selected: dict[str, dict[str, Any]] = {}
    for key, entry in load_manifest(root).items():
        if wanted is not None and (entry["source"], entry["symbol"]) not in wanted:
            continue
        selected[key] = {
            field: entry[field]
            for field in (
                "source",
                "symbol",
                "year",
                "price_side",
                "rows",
                "first_ts",
                "last_ts",
                "content_sha256",
                "loader_version",
            )
        }
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


__all__ = [
    "LOADER_VERSION",
    "M1_COLUMNS",
    "FileEntry",
    "content_hash",
    "data_version",
    "dataset_range",
    "load_manifest",
    "parquet_path",
    "read_raw_m1",
    "verify_store",
    "write_m1",
]
