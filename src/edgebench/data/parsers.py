"""Parsers for raw downloads into the canonical M1 frame (docs/CONTRACT.md section 3).

Binance public archives (data.binance.vision) are headerless 12-column CSV, often zipped, and their
timestamps are milliseconds before 2025 and microseconds after: the unit is detected from the
magnitude of the values. Dukascopy exports (for example from ``dukascopy-node``) have a header with
a ``timestamp`` column in UTC. Dukascopy candles are single-sided, so bid and ask files are merged
with ``merge_ask``.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO

import numpy as np
import pandas as pd

from edgebench.data.errors import DataError
from edgebench.data.schema import ASK_COLUMNS, PRICE_COLUMNS, TS_DTYPE, normalize_m1

Source = str | Path | IO[bytes] | IO[str]

# Epoch magnitude thresholds: below 1e11 seconds, below 1e14 milliseconds, below 1e17
# microseconds, otherwise nanoseconds. 1e11 s is year 5138; 1e14 ms is 1973 to 5138.
_UNIT_LIMITS: tuple[tuple[float, str], ...] = ((1e11, "s"), (1e14, "ms"), (1e17, "us"))
_MIN_YEAR, _MAX_YEAR = 2005, 2100
_BINANCE_COLUMNS = ["ts_open", "open", "high", "low", "close", "volume"]


def detect_epoch_unit(values: pd.Series) -> str:
    """Unit of an epoch column (``s``, ``ms``, ``us`` or ``ns``) from its median magnitude."""
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        raise DataError("no numeric timestamps to detect the unit from")
    magnitude = float(numeric.abs().median())
    for limit, unit in _UNIT_LIMITS:
        if magnitude < limit:
            return unit
    return "ns"


def epoch_to_utc(values: pd.Series) -> pd.Series:
    """Convert an epoch column of unknown unit to ``datetime64[ns, UTC]`` and sanity-check it."""
    unit = detect_epoch_unit(values)
    numeric = pd.to_numeric(values, errors="raise").astype("int64")
    # Convert via int64 nanoseconds so the result never depends on pandas' default resolution.
    factor = {"s": 10**9, "ms": 10**6, "us": 10**3, "ns": 1}[unit]
    converted = pd.to_datetime(numeric * factor, unit="ns", utc=True).astype(TS_DTYPE)
    years = converted.dt.year
    if years.min() < _MIN_YEAR or years.max() > _MAX_YEAR:
        raise DataError(
            f"timestamps decoded as {unit} fall outside {_MIN_YEAR}-{_MAX_YEAR} "
            f"({years.min()}-{years.max()}); the unit detection is not trustworthy"
        )
    return converted


def parse_binance_klines(source: Source) -> pd.DataFrame:
    """Parse one Binance kline file (CSV or single-file zip, with or without a header row)."""
    raw = pd.read_csv(
        source,
        header=None,
        usecols=range(6),
        names=_BINANCE_COLUMNS,
        dtype=str,
        compression="infer",
    )
    if raw.empty:
        raise DataError("empty Binance file")
    first = str(raw.iloc[0, 0]).strip()
    if not first.lstrip("-").isdigit():
        raw = raw.iloc[1:]  # header row such as "open_time,open,high,..."
    if raw.empty:
        raise DataError("Binance file has a header but no rows")
    frame = pd.DataFrame({"ts_open": epoch_to_utc(raw["ts_open"])})
    for column in [*PRICE_COLUMNS, "volume"]:
        frame[column] = pd.to_numeric(raw[column], errors="raise").to_numpy()
    return normalize_m1(frame)


def parse_dukascopy_csv(source: Source) -> pd.DataFrame:
    """Parse a Dukascopy M1 export. A missing volume column is filled with 0.0."""
    raw = pd.read_csv(source, compression="infer")
    raw.columns = [str(c).strip().lower() for c in raw.columns]
    ts_name = next((c for c in ("timestamp", "time", "datetime", "date") if c in raw.columns), None)
    if ts_name is None:
        raise DataError(f"no timestamp column in {list(raw.columns)}")
    missing = [c for c in PRICE_COLUMNS if c not in raw.columns]
    if missing:
        raise DataError(f"missing price columns: {missing}")
    stamps = raw[ts_name]
    if pd.api.types.is_numeric_dtype(stamps):
        ts = epoch_to_utc(stamps)
    else:
        ts = pd.to_datetime(stamps, utc=True).astype(TS_DTYPE)
    frame = pd.DataFrame({"ts_open": ts})
    for column in PRICE_COLUMNS:
        frame[column] = raw[column].to_numpy()
    frame["volume"] = raw["volume"].to_numpy() if "volume" in raw.columns else 0.0
    return normalize_m1(frame)


def merge_ask(bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    """Attach ask OHLC columns to a bid frame. Minutes without an ask bar keep NaN."""
    renamed = ask[["ts_open", *PRICE_COLUMNS]].rename(columns=dict(zip(PRICE_COLUMNS, ASK_COLUMNS, strict=True)))
    merged = bid.drop(columns=[c for c in ASK_COLUMNS if c in bid.columns]).merge(
        renamed, on="ts_open", how="left", validate="one_to_one"
    )
    for column in ASK_COLUMNS:
        merged[column] = merged[column].astype(np.float64)
    return merged
