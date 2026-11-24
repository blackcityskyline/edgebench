"""Streaming Wilder ATR (docs/CONTRACT.md section 2.2).

``update`` takes one closed bar and returns the ATR known at that bar's close, or None while fewer
than ``period`` bars have been seen. The first true range of the stream is ``high - low`` (there is
no previous close); the first ATR is the mean of the first ``period`` true ranges, then Wilder
smoothing ``atr = (atr * (period - 1) + tr) / period``.
"""

from __future__ import annotations

from edgebench.contracts import Bar


class WilderATR:
    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError("period must be >= 1")
        self.period = period
        self._count = 0
        self._sum = 0.0
        self._prev_close: float | None = None
        self._atr: float | None = None

    @property
    def value(self) -> float | None:
        return self._atr

    def update(self, bar: Bar) -> float | None:
        span = bar.high - bar.low
        if self._prev_close is None:
            true_range = span
        else:
            true_range = max(
                span, abs(bar.high - self._prev_close), abs(bar.low - self._prev_close)
            )
        self._prev_close = bar.close
        self._count += 1
        if self._count < self.period:
            self._sum += true_range
        elif self._count == self.period:
            self._atr = (self._sum + true_range) / self.period
        elif self._atr is not None:
            self._atr = (self._atr * (self.period - 1) + true_range) / self.period
        return self._atr
