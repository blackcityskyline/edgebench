"""Bars and the time conventions of docs/CONTRACT.md section 2.1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

TIMEFRAME_SECONDS: dict[str, int] = {"M1": 60, "M3": 180, "H1": 3600}


def require_utc(ts: datetime, name: str) -> None:
    """Raise ValueError unless ``ts`` is timezone-aware with a zero UTC offset."""
    if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be timezone-aware UTC, got {ts!r}")


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV bar identified by ``ts_open``; available at ``ts_close``."""

    ts_open: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    tf: str
    complete: bool = True

    def __post_init__(self) -> None:
        require_utc(self.ts_open, "ts_open")
        if self.tf not in TIMEFRAME_SECONDS:
            raise ValueError(f"unknown timeframe {self.tf!r}")
        if self.high < self.low:
            raise ValueError("high < low")
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("open/close outside the high-low range")
        if self.volume < 0:
            raise ValueError("negative volume")

    @property
    def ts_close(self) -> datetime:
        """Moment the bar becomes available to a decision (contract 2.1)."""
        return self.ts_open + timedelta(seconds=TIMEFRAME_SECONDS[self.tf])
