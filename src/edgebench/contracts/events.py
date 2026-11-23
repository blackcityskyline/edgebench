"""Observations and touch-episode events (docs/CONTRACT.md section 4.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from edgebench.contracts.bars import require_utc
from edgebench.contracts.zones import Direction


@dataclass(frozen=True, slots=True)
class Observation:
    """One pattern detection, available at ``ts_decision`` (the close of its last bar)."""

    detector: str
    ts_decision: datetime
    direction: Direction
    refs: dict[str, float] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_utc(self.ts_decision, "ts_decision")


@dataclass(frozen=True, slots=True)
class Event:
    """One touch episode of a zone. Decision times live on candidates, not here."""

    event_id: str
    zone_id: str
    instrument: str
    direction: Direction
    touch_start: datetime
    session: str | None = None
    features: dict[str, float] = field(default_factory=dict)
    observations: tuple[Observation, ...] = ()

    def __post_init__(self) -> None:
        require_utc(self.touch_start, "touch_start")
