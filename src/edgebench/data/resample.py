"""Derive M3 and H1 bars from M1 (docs/CONTRACT.md section 3).

Labels are bar open times, buckets are left-closed and aligned to the clock (M3 starts at minutes
0, 3, 6, ...; H1 at the top of the hour). A bucket built from fewer than ``min_m1_fraction`` of its
expected M1 bars is flagged ``complete=False``: zones are never built from such bars. Gaps are never
filled with synthetic bars.
"""

from __future__ import annotations

import pandas as pd

from edgebench.contracts import TIMEFRAME_SECONDS
from edgebench.data.errors import DataError
from edgebench.data.schema import ASK_COLUMNS, TS_DTYPE

# Placeholder until the owner decides; thinly traded crypto can legitimately miss minutes, because
# Binance emits no kline for a minute without trades.
DEFAULT_MIN_M1_FRACTION = 0.8


def resample(
    m1: pd.DataFrame, tf: str, min_m1_fraction: float = DEFAULT_MIN_M1_FRACTION
) -> pd.DataFrame:
    """Aggregate an M1 frame to ``tf`` (``M1``, ``M3`` or ``H1``).

    Returns ``ts_open, open, high, low, close, volume`` (plus ask columns when present),
    ``n_m1`` (M1 bars used) and ``complete``.
    """
    if tf not in TIMEFRAME_SECONDS:
        raise DataError(f"unknown timeframe {tf!r}")
    if not 0 < min_m1_fraction <= 1:
        raise DataError("min_m1_fraction must be in (0, 1]")
    if not m1["ts_open"].is_monotonic_increasing:
        raise DataError("M1 frame must be sorted by ts_open")
    seconds = TIMEFRAME_SECONDS[tf]
    expected = seconds // 60
    bucket = m1["ts_open"].dt.floor(f"{seconds}s").rename("bucket")
    spec: dict[str, tuple[str, str]] = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "volume": ("volume", "sum"),
    }
    if all(c in m1.columns for c in ASK_COLUMNS):
        spec |= {
            "ask_open": ("ask_open", "first"),
            "ask_high": ("ask_high", "max"),
            "ask_low": ("ask_low", "min"),
            "ask_close": ("ask_close", "last"),
        }
    spec["n_m1"] = ("open", "size")
    out = m1.groupby(bucket, sort=True).agg(**spec).reset_index().rename(columns={"bucket": "ts_open"})
    out["ts_open"] = out["ts_open"].astype(TS_DTYPE)
    out["n_m1"] = out["n_m1"].astype("int64")
    out["complete"] = (out["n_m1"] / expected) >= min_m1_fraction
    return out
