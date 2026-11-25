"""Incremental M1 -> M3/H1 aggregation for the streaming engine (same rules as ``resample``)."""

from __future__ import annotations

from datetime import UTC, datetime

from edgebench.contracts import TIMEFRAME_SECONDS, Bar
from edgebench.data.resample import DEFAULT_MIN_M1_FRACTION


class Aggregator:
    """Builds ``tf`` bars from closed M1 bars.

    A bar is emitted as soon as the last M1 minute of its bucket has closed (at its ``ts_close``),
    or, when that minute is missing, when the first bar of a later bucket arrives. A bucket with
    fewer than ``min_m1_fraction`` of its M1 bars is emitted with ``complete=False``.
    """

    def __init__(self, tf: str, min_m1_fraction: float = DEFAULT_MIN_M1_FRACTION) -> None:
        if tf not in ("M3", "H1"):
            raise ValueError("Aggregator supports M3 and H1")
        self._tf = tf
        self._seconds = TIMEFRAME_SECONDS[tf]
        self._expected = self._seconds // 60
        self._min = min_m1_fraction
        self._bucket: int | None = None
        self._o = self._h = self._lo = self._c = self._v = 0.0
        self._n = 0

    def push(self, bar: Bar) -> list[Bar]:
        if bar.tf != "M1":
            raise ValueError("Aggregator needs M1 bars")
        out: list[Bar] = []
        bucket = int(bar.ts_open.timestamp()) // self._seconds * self._seconds
        if self._bucket is not None and bucket != self._bucket:
            out.append(self._emit())
        if self._bucket is None:
            self._bucket = bucket
            self._o, self._h, self._lo, self._c, self._v, self._n = (
                bar.open, bar.high, bar.low, bar.close, bar.volume, 1,
            )  # fmt: skip
        else:
            self._h, self._lo = max(self._h, bar.high), min(self._lo, bar.low)
            self._c, self._v, self._n = bar.close, self._v + bar.volume, self._n + 1
        if int(bar.ts_close.timestamp()) == bucket + self._seconds:
            out.append(self._emit())
        return out

    def _emit(self) -> Bar:
        assert self._bucket is not None
        bar = Bar(
            datetime.fromtimestamp(self._bucket, UTC),
            self._o,
            self._h,
            self._lo,
            self._c,
            self._v,
            self._tf,
            complete=self._n / self._expected >= self._min,
        )
        self._bucket = None
        return bar
