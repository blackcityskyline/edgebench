"""Sliding window of consecutive complete bars shared by the zone detectors.

A pattern is only formed from bars that are complete and directly adjacent in time. A time gap
(weekend, outage) or an incomplete bar empties the window, so no pattern is ever drawn across a
hole in the data (docs/CONTRACT.md 4.3).
"""

from __future__ import annotations

from collections import deque

from edgebench.contracts import Bar


class BarWindow:
    def __init__(self, size: int, tf: str = "H1") -> None:
        if size < 1:
            raise ValueError("size must be >= 1")
        self._bars: deque[Bar] = deque(maxlen=size)
        self._tf = tf

    @property
    def bars(self) -> tuple[Bar, ...]:
        return tuple(self._bars)

    def push(self, bar: Bar) -> bool:
        """Add ``bar``; True when the window now holds ``size`` consecutive complete bars."""
        if bar.tf != self._tf:
            raise ValueError(f"expected {self._tf} bars, got {bar.tf}")
        if not bar.complete:
            self._bars.clear()
            return False
        if self._bars and bar.ts_open != self._bars[-1].ts_close:
            self._bars.clear()
        self._bars.append(bar)
        return len(self._bars) == self._bars.maxlen
