"""Day-block bootstrap (docs/CONTRACT.md section 7.4).

Trades inside one day are strongly correlated (shadow trades of one episode, one session), so the
resampling unit is the day: draw days with replacement and recompute the pooled mean.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Interval:
    mean: float
    lo: float
    hi: float
    n: int
    days: int

    def excludes_zero(self) -> bool:
        return self.lo > 0 or self.hi < 0


def _per_day(
    values: npt.NDArray[np.float64], days: npt.NDArray[np.str_], universe: npt.NDArray[np.str_]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    idx = np.searchsorted(universe, days)
    sums = np.bincount(idx, weights=values, minlength=len(universe))
    counts = np.bincount(idx, minlength=len(universe)).astype(float)
    return sums, counts


def _interval(
    stats: npt.NDArray[np.float64], point: float, n: int, days: int, alpha: float
) -> Interval:
    lo, hi = np.nanpercentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return Interval(point, float(lo), float(hi), n, days)


def day_bootstrap_mean(
    values: npt.ArrayLike,
    days: npt.ArrayLike,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Interval:
    """Mean with a percentile interval from resampling whole days."""
    v = np.asarray(values, dtype=float)
    d = np.asarray(days).astype(str)
    if len(v) == 0:
        return Interval(float("nan"), float("nan"), float("nan"), 0, 0)
    universe = np.unique(d)
    sums, counts = _per_day(v, d, universe)
    draw = np.random.default_rng(seed).integers(0, len(universe), size=(n_boot, len(universe)))
    boot = sums[draw].sum(axis=1) / counts[draw].sum(axis=1)
    return _interval(boot, float(v.mean()), len(v), len(universe), alpha)


def day_bootstrap_diff(
    a_values: npt.ArrayLike,
    a_days: npt.ArrayLike,
    b_values: npt.ArrayLike,
    b_days: npt.ArrayLike,
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> Interval:
    """``mean(a) - mean(b)`` with days resampled jointly from both groups."""
    av, bv = np.asarray(a_values, dtype=float), np.asarray(b_values, dtype=float)
    ad, bd = np.asarray(a_days).astype(str), np.asarray(b_days).astype(str)
    if len(av) == 0 or len(bv) == 0:
        return Interval(float("nan"), float("nan"), float("nan"), len(av), 0)
    universe = np.union1d(ad, bd)
    a_sum, a_cnt = _per_day(av, ad, universe)
    b_sum, b_cnt = _per_day(bv, bd, universe)
    draw = np.random.default_rng(seed).integers(0, len(universe), size=(n_boot, len(universe)))
    with np.errstate(invalid="ignore", divide="ignore"):
        boot = a_sum[draw].sum(1) / a_cnt[draw].sum(1) - b_sum[draw].sum(1) / b_cnt[draw].sum(1)
    return _interval(boot, float(av.mean() - bv.mean()), len(av), len(universe), alpha)
