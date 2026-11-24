"""Public data API: split-aware loading and conversion to ``Bar`` objects.

``load_m1`` is the only supported way for research code to read prices. ``dev`` returns data inside
the dev bounds; ``holdout`` additionally needs a ``HoldoutRequest`` (and the owner's token).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd

from edgebench.contracts import Bar
from edgebench.data.errors import DataError
from edgebench.data.holdout import authorize_holdout
from edgebench.data.resample import DEFAULT_MIN_M1_FRACTION, resample
from edgebench.data.splits import SplitBounds
from edgebench.data.store import read_raw_m1

Split = Literal["dev", "holdout"]


@dataclass(frozen=True)
class HoldoutRequest:
    reason: str
    config_hash: str
    code_commit: str
    ledger: Path


def load_m1(
    root: Path,
    source: str,
    symbol: str,
    bounds: SplitBounds,
    split: Split = "dev",
    holdout: HoldoutRequest | None = None,
) -> pd.DataFrame:
    """M1 bars of one instrument inside the requested split."""
    if split == "dev":
        frame = read_raw_m1(
            root,
            source,
            symbol,
            start=pd.Timestamp(bounds.dev_start),
            end=pd.Timestamp(bounds.dev_end),
        )
    elif split == "holdout":
        if holdout is None:
            raise DataError("split='holdout' needs a HoldoutRequest")
        authorize_holdout(holdout.ledger, holdout.reason, holdout.config_hash, holdout.code_commit)
        frame = read_raw_m1(root, source, symbol, start=pd.Timestamp(bounds.holdout_start))
    else:
        raise DataError(f"unknown split {split!r}")
    if frame.empty:
        raise DataError(f"{source}/{symbol} has no data in the {split} split")
    return frame


def load_bars(
    root: Path,
    source: str,
    symbol: str,
    bounds: SplitBounds,
    tf: str,
    split: Split = "dev",
    holdout: HoldoutRequest | None = None,
    min_m1_fraction: float = DEFAULT_MIN_M1_FRACTION,
) -> pd.DataFrame:
    """Bars at ``tf`` (``M1``, ``M3`` or ``H1``) with ``n_m1`` and ``complete`` columns."""
    m1 = load_m1(root, source, symbol, bounds, split, holdout)
    return resample(m1, tf, min_m1_fraction)


def iter_bars(frame: pd.DataFrame, tf: str) -> Iterator[Bar]:
    """Yield ``Bar`` objects from a resampled frame (the input of the streaming engine)."""
    complete = frame["complete"] if "complete" in frame.columns else None
    for i, row in enumerate(frame.itertuples(index=False)):
        yield Bar(
            ts_open=row.ts_open.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
            tf=tf,
            complete=True if complete is None else bool(complete.iloc[i]),
        )
