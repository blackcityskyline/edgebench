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
    nominal_spread: float | None = None  # spread used by filters; fills use ``spread``

    def __post_init__(self) -> None:
        if min(self.spread, self.slippage, self.commission_bps, self.nominal_spread or 0.0) < 0:
            raise ValueError("costs must not be negative")

    @property
    def filter_spread(self) -> float:
        """Spread that sizes stop buffers and the minimum stop. It does not move with a cost
        multiplier, so cost-sensitivity runs evaluate the same candidates."""
        return self.spread if self.nominal_spread is None else self.nominal_spread

    @classmethod
    def from_spec(cls, spec: InstrumentSpec, mult: float = 1.0) -> CostModel:
        """Costs of an instrument, with spread, slippage and commission scaled by ``mult``."""
        return cls(
            spec.spread * mult,
            spec.slippage_spreads * spec.spread * mult,
            spec.commission_bps * mult,
            nominal_spread=spec.spread,
        )
