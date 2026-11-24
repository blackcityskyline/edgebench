"""Synthetic M1 data for tests and gates, so CI never needs real market data.

``make_m1`` is a seeded random walk (same seed, same frame). ``frame_from_ohlc`` builds hand-made
bar sequences with a known answer, which is what detector tests and fixtures use.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from edgebench.data.schema import ASK_COLUMNS, TS_DTYPE, normalize_m1

DEFAULT_START = datetime(2024, 1, 1, tzinfo=UTC)


def make_m1(
    minutes: int,
    seed: int = 0,
    start: datetime = DEFAULT_START,
    start_price: float = 100.0,
    vol_bp: float = 2.0,
    weekends: bool = False,
    ask_spread: float | None = None,
) -> pd.DataFrame:
    """Random-walk M1 bars. ``vol_bp`` is the per-minute return volatility in basis points.

    ``weekends=True`` removes Saturday and Sunday (UTC) like a forex feed. ``ask_spread`` adds ask
    columns equal to the bid columns plus that spread.
    """
    if minutes < 1:
        raise ValueError("minutes must be >= 1")
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, vol_bp / 1e4, size=minutes)
    close = start_price * np.exp(np.cumsum(returns))
    open_ = np.concatenate([[start_price], close[:-1]])
    wick_up = np.abs(rng.normal(0.0, vol_bp / 2e4, size=minutes))
    wick_down = np.abs(rng.normal(0.0, vol_bp / 2e4, size=minutes))
    high = np.maximum(open_, close) * (1.0 + wick_up)
    low = np.minimum(open_, close) * (1.0 - wick_down)
    volume = rng.uniform(1.0, 100.0, size=minutes)
    ts = pd.date_range(start=start, periods=minutes, freq="min", tz="UTC")
    frame = pd.DataFrame(
        {"ts_open": ts, "open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )
    if ask_spread is not None:
        for bid_col, ask_col in zip(["open", "high", "low", "close"], ASK_COLUMNS, strict=True):
            frame[ask_col] = frame[bid_col] + ask_spread
    if weekends:
        frame = frame[frame["ts_open"].dt.day_of_week < 5]
    return normalize_m1(frame)


def frame_from_ohlc(
    rows: Sequence[tuple[float, float, float, float]],
    start: datetime = DEFAULT_START,
    volume: float = 1.0,
) -> pd.DataFrame:
    """One M1 bar per ``(open, high, low, close)`` row, on consecutive minutes from ``start``."""
    if not rows:
        raise ValueError("rows must not be empty")
    ts = pd.date_range(start=start, periods=len(rows), freq="min", tz="UTC").astype(TS_DTYPE)
    frame = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    frame.insert(0, "ts_open", ts)
    frame["volume"] = volume
    return normalize_m1(frame)
