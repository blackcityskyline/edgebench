"""Canonical M1 frame: normalization, validation, gap detection (docs/CONTRACT.md section 3).

An M1 frame has one row per minute that had trades or quotes. Missing minutes are never filled.
Columns: ``ts_open`` (``datetime64[ns, UTC]``, the bar's open time), ``open``, ``high``, ``low``,
``close``, ``volume`` (all float64) and optionally ``ask_open``, ``ask_high``, ``ask_low``,
``ask_close`` (float64, NaN where unknown).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from edgebench.data.errors import DataError

TS_DTYPE = "datetime64[ns, UTC]"
PRICE_COLUMNS = ["open", "high", "low", "close"]
M1_COLUMNS = ["ts_open", *PRICE_COLUMNS, "volume"]
ASK_COLUMNS = ["ask_open", "ask_high", "ask_low", "ask_close"]
MAX_REPORTED = 5


def normalize_m1(df: pd.DataFrame) -> pd.DataFrame:
    """Return a clean copy: canonical columns and dtypes, sorted, duplicates resolved.

    Identical duplicate rows are dropped; rows that share a timestamp but differ raise DataError.
    """
    missing = [c for c in M1_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(f"missing columns: {missing}")
    keep = M1_COLUMNS + [c for c in ASK_COLUMNS if c in df.columns]
    out = df[keep].copy()
    out["ts_open"] = pd.to_datetime(out["ts_open"], utc=True).astype(TS_DTYPE)
    for column in keep[1:]:
        out[column] = out[column].astype("float64")
    out = out.sort_values("ts_open", kind="stable")
    if out["ts_open"].duplicated().any():
        deduped = out.drop_duplicates()
        if deduped["ts_open"].duplicated().any():
            raise DataError("conflicting rows share a timestamp")
        out = deduped
    return out.reset_index(drop=True)


def validate_m1(df: pd.DataFrame) -> list[str]:
    """Return a list of problems (empty when the frame is a valid M1 frame)."""
    problems: list[str] = []
    missing = [c for c in M1_COLUMNS if c not in df.columns]
    if missing:
        return [f"missing columns: {missing}"]
    if str(df["ts_open"].dtype) != TS_DTYPE:
        problems.append(f"ts_open dtype is {df['ts_open'].dtype}, expected {TS_DTYPE}")
        return problems
    if len(df) == 0:
        return ["frame is empty"]
    if not df["ts_open"].is_monotonic_increasing or df["ts_open"].duplicated().any():
        problems.append("ts_open is not strictly increasing")
    values = df[M1_COLUMNS[1:]].to_numpy(dtype="float64")
    if not np.isfinite(values).all():
        problems.append("non-finite values in price or volume columns")
        return problems
    o, h, low, c, v = (df[col].to_numpy(dtype="float64") for col in M1_COLUMNS[1:])
    checks = {
        "non-positive prices": (np.minimum(np.minimum(o, h), np.minimum(low, c)) <= 0).sum(),
        "high < low": (h < low).sum(),
        "high below open/close": (h < np.maximum(o, c)).sum(),
        "low above open/close": (low > np.minimum(o, c)).sum(),
        "negative volume": (v < 0).sum(),
    }
    problems += [f"{name}: {int(n)} row(s)" for name, n in checks.items() if n]
    return problems


def assert_valid_m1(df: pd.DataFrame) -> None:
    problems = validate_m1(df)
    if problems:
        raise DataError("invalid M1 frame: " + "; ".join(problems[:MAX_REPORTED]))


def find_gaps(df: pd.DataFrame, min_missing_minutes: int = 1) -> pd.DataFrame:
    """Gaps between consecutive M1 bars.

    Returns columns ``start`` (first missing minute), ``end`` (open of the next bar, exclusive) and
    ``missing_minutes``, for gaps with at least ``min_missing_minutes`` missing minutes.
    """
    ts = df["ts_open"]
    step = ts.diff()
    missing = (step / pd.Timedelta(minutes=1)).fillna(1).astype("int64") - 1
    mask = missing >= min_missing_minutes
    gaps = pd.DataFrame(
        {
            "start": (ts.shift(1) + pd.Timedelta(minutes=1))[mask],
            "end": ts[mask],
            "missing_minutes": missing[mask],
        }
    )
    return gaps.reset_index(drop=True)
