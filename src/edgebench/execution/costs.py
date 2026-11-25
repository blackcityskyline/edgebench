"""Cost model of one instrument (docs/CONTRACT.md section 2.2)."""

from __future__ import annotations

from dataclasses import dataclass

from edgebench.config.environment import InstrumentSpec


@dataclass(frozen=True, slots=True)
class CostModel:
    """Fixed spread, stop slippage and per-side commission, all in price units except bps."""

    spread: float
    slippage: float = 0.0
    commission_bps: float = 0.0

    def __post_init__(self) -> None:
        if self.spread < 0 or self.slippage < 0 or self.commission_bps < 0:
            raise ValueError("costs must not be negative")

    @classmethod
    def from_spec(cls, spec: InstrumentSpec) -> CostModel:
        return cls(spec.spread, spec.slippage_spreads * spec.spread, spec.commission_bps)
