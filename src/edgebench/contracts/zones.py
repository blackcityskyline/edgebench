"""Zones and their lifecycle events (docs/CONTRACT.md sections 4.1 and 4.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from edgebench.contracts.bars import require_utc


class ZoneKind(StrEnum):
    FVG = "FVG"
    FRACTAL = "FRACTAL"


class Direction(StrEnum):
    """BULL = support / long bias, BEAR = resistance / short bias."""

    BULL = "BULL"
    BEAR = "BEAR"


class ZoneEventType(StrEnum):
    CREATED = "CREATED"
    TOUCH_START = "TOUCH_START"
    TOUCH_END = "TOUCH_END"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class Zone:
    """An H1 context zone.

    FVG: ``formed_at == known_at`` is the close of the third bar.
    FRACTAL: ``extreme_ts`` is the open of the pivot bar, ``formed_at`` is the close of the
    pivot bar, and ``known_at`` is the close of the ``right``-th bar after the pivot. The level
    must not be used before ``known_at``.
    """

    zone_id: str
    instrument: str
    kind: ZoneKind
    direction: Direction
    low: float
    high: float
    formed_at: datetime
    known_at: datetime
    extreme_ts: datetime | None = None
    params_hash: str = ""

    def __post_init__(self) -> None:
        require_utc(self.formed_at, "formed_at")
        require_utc(self.known_at, "known_at")
        if self.low > self.high:
            raise ValueError("zone low > high")
        if self.known_at < self.formed_at:
            raise ValueError("known_at must not precede formed_at")
        if self.kind is ZoneKind.FRACTAL:
            if self.low != self.high:
                raise ValueError("a fractal zone is a single level (low == high)")
            if self.extreme_ts is None:
                raise ValueError("a fractal zone needs extreme_ts")
            require_utc(self.extreme_ts, "extreme_ts")
            if self.extreme_ts >= self.formed_at:
                raise ValueError("extreme_ts must precede formed_at")
        elif self.known_at != self.formed_at:
            raise ValueError("an FVG is known at the moment it is formed")


@dataclass(frozen=True, slots=True)
class ZoneEvent:
    zone_id: str
    ts: datetime
    type: ZoneEventType

    def __post_init__(self) -> None:
        require_utc(self.ts, "ts")
