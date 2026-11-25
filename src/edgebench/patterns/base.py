"""Pattern detector interface (docs/CONTRACT.md section 4.4).

A detector sees one closed M1 bar at a time together with a ``PatternContext`` and returns the
observations completed by that bar. Observations are stamped with the close of that bar. Detectors
may keep state between calls (an episode is one stream); ``reset`` clears it for the next episode.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from edgebench.contracts import Bar, Direction, Observation, Zone


@dataclass(frozen=True, slots=True)
class PatternContext:
    """Everything a detector may use at the close of the current bar.

    ``history`` holds closed M1 bars, oldest first, and its last element is the current bar.
    It may start before the touch (look-back). ``m3_history`` holds complete M3 bars whose
    ``ts_close`` is not after the current bar's close. ``h1_levels`` are H1 fractal levels on
    the sweep side that are already known (``known_at`` passed): lows for a BULL zone, highs
    for a BEAR zone. ``atr_m1`` is the M1 ATR known before the current bar.
    """

    zone: Zone
    episode_index: int
    touch_start: datetime
    atr_m1: float
    history: tuple[Bar, ...]
    m3_history: tuple[Bar, ...] = ()
    h1_levels: tuple[float, ...] = ()
    bars_since_touch: int = 0

    def __post_init__(self) -> None:
        if not self.history:
            raise ValueError("history must contain at least the current bar")
        if self.atr_m1 <= 0:
            raise ValueError("atr_m1 must be positive")

    @property
    def direction(self) -> Direction:
        return self.zone.direction


class PatternDetector(Protocol):
    name: str

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]: ...

    def reset(self) -> None: ...


def pivot_levels(closed: Sequence[Bar], side: Direction, left: int, right: int) -> list[float]:
    """Unpierced fractal levels among closed bars (the current bar must not be included).

    BULL looks for pivot lows (strictly lower than ``left`` bars before and ``right`` after),
    BEAR for pivot highs. A pivot counts only after its ``right`` bars have closed, and a level
    already traded through by a later bar is dropped.
    """
    levels: list[float] = []
    for j in range(left, len(closed) - right):
        if side is Direction.BULL:
            level = closed[j].low
            ok = all(closed[k].low > level for k in range(j - left, j + right + 1) if k != j)
            pierced = any(b.low < level for b in closed[j + right + 1 :])
        else:
            level = closed[j].high
            ok = all(closed[k].high < level for k in range(j - left, j + right + 1) if k != j)
            pierced = any(b.high > level for b in closed[j + right + 1 :])
        if ok and not pierced:
            levels.append(level)
    return levels
