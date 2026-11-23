"""Candidate trades and executed trades (docs/CONTRACT.md sections 2.2, 4.1, 4.5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from edgebench.contracts.bars import require_utc


class Side(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1


class ExitReason(StrEnum):
    STOP = "STOP"
    TARGET = "TARGET"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """A candidate trade created by one trigger; the unit for the evaluator and labels."""

    candidate_id: str
    event_id: str
    trigger: str
    ts_decision: datetime
    side: Side
    entry_policy: str
    entry_ref: float
    stop_price: float

    def __post_init__(self) -> None:
        require_utc(self.ts_decision, "ts_decision")
        if self.side is Side.LONG and self.stop_price >= self.entry_ref:
            raise ValueError("long stop must be below the entry reference")
        if self.side is Side.SHORT and self.stop_price <= self.entry_ref:
            raise ValueError("short stop must be above the entry reference")


@dataclass(frozen=True, slots=True)
class Trade:
    """An executed candidate. ``trade_id`` equals the candidate's ``candidate_id``.

    ``ladder`` maps ``"stop"`` and each target level in R (``"1"``, ``"2"``, ...) to the time it
    was first reached, or None. ``r_net`` is net of spread, slippage and commission.
    """

    trade_id: str
    side: Side
    entry_ts: datetime
    entry_fill: float
    stop_price: float
    risk_distance: float
    exit_ts: datetime
    exit_reason: ExitReason
    exit_fill: float
    r_net: float
    mfe_r: float
    mae_r: float
    ambiguous_bars: int
    cost_r: float
    ladder: dict[str, datetime | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_utc(self.entry_ts, "entry_ts")
        require_utc(self.exit_ts, "exit_ts")
        if self.risk_distance <= 0:
            raise ValueError("risk_distance must be positive")
        if self.exit_ts < self.entry_ts:
            raise ValueError("exit before entry")
