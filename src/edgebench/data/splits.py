"""Dev/holdout boundaries and walk-forward folds (docs/CONTRACT.md section 7.1).

All boundaries are UTC midnights and the same calendar boundaries apply to every instrument, so a
holdout period for one instrument cannot leak into the dev period of another. The holdout start is
**frozen**: derive it once, write it to ``config/splits.yaml``, and never recompute it, otherwise
newly downloaded data would move the boundary and turn data you have already looked at into holdout
(or the reverse).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from edgebench.config import SplitsConfig
from edgebench.data.errors import DataError

MIN_HORIZON_DAYS = 60


@dataclass(frozen=True)
class SplitBounds:
    dev_start: datetime
    dev_end: datetime  # exclusive; holdout_start minus the embargo
    holdout_start: datetime
    embargo_days: int
    derived: bool  # True when holdout_start was computed, not taken from the config


@dataclass(frozen=True)
class Fold:
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _floor_day(moment: datetime) -> datetime:
    return datetime(moment.year, moment.month, moment.day, tzinfo=UTC)


def derive_bounds(first: datetime, last_end: datetime, cfg: SplitsConfig) -> SplitBounds:
    """Split bounds for data covering ``[first, last_end)``. Explicit config dates win."""
    if first.tzinfo is None or last_end.tzinfo is None:
        raise DataError("horizon timestamps must be timezone-aware")
    horizon = last_end - first
    if cfg.holdout_start is not None:
        holdout_start = _midnight(cfg.holdout_start)
        derived = False
    else:
        if horizon < timedelta(days=MIN_HORIZON_DAYS):
            raise DataError(f"horizon is {horizon.days} days; need at least {MIN_HORIZON_DAYS}")
        holdout_start = _floor_day(last_end - horizon * cfg.holdout_fraction)
        derived = True
    embargo = timedelta(days=cfg.embargo_days)
    dev_start = _midnight(cfg.dev_start) if cfg.dev_start is not None else _floor_day(first)
    latest_dev_end = holdout_start - embargo
    dev_end = _midnight(cfg.dev_end) if cfg.dev_end is not None else latest_dev_end
    if dev_end > latest_dev_end:
        raise DataError("dev_end must be at least embargo_days before holdout_start")
    if dev_end - dev_start < timedelta(days=MIN_HORIZON_DAYS // 2):
        raise DataError("dev period is too short")
    return SplitBounds(dev_start, dev_end, holdout_start, cfg.embargo_days, derived)


def walk_forward_folds(bounds: SplitBounds, folds: int) -> list[Fold]:
    """Expanding-window folds inside dev: train on everything before each test segment.

    Dev is cut into ``folds + 1`` equal day-aligned segments. Fold ``i`` trains on segments before
    segment ``i`` (minus the embargo) and tests on segment ``i``.
    """
    if folds < 1:
        raise DataError("folds must be >= 1")
    total = bounds.dev_end - bounds.dev_start
    embargo = timedelta(days=bounds.embargo_days)

    def edge(k: int) -> datetime:
        return _floor_day(bounds.dev_start + total * k / (folds + 1))

    result: list[Fold] = []
    for i in range(1, folds + 1):
        test_start, test_end = edge(i), (edge(i + 1) if i < folds else bounds.dev_end)
        train_end = test_start - embargo
        if train_end <= bounds.dev_start:
            raise DataError("embargo leaves no training data in the first fold")
        result.append(Fold(bounds.dev_start, train_end, test_start, test_end))
    return result
