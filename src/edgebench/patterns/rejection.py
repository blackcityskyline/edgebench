"""Rejection wick: a long wick into the zone and a close back in the reaction direction."""

from __future__ import annotations

from edgebench.config.schema import RejectionConfig
from edgebench.contracts import Bar, Direction, Observation
from edgebench.patterns.base import PatternContext


class RejectionDetector:
    name = "rejection"

    def __init__(self, cfg: RejectionConfig) -> None:
        self._cfg = cfg

    def reset(self) -> None:
        return None

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        zone, rng = ctx.zone, bar.high - bar.low
        if rng <= 0:
            return []
        if zone.direction is Direction.BULL:
            if bar.low > zone.high:  # the bar must reach the zone
                return []
            wick = min(bar.open, bar.close) - bar.low
            close_pos = (bar.close - bar.low) / rng
        else:
            if bar.high < zone.low:
                return []
            wick = bar.high - max(bar.open, bar.close)
            close_pos = (bar.high - bar.close) / rng
        ratio = wick / rng
        if ratio < self._cfg.min_wick_ratio or close_pos < 1 - self._cfg.close_zone:
            return []
        extreme = bar.low if zone.direction is Direction.BULL else bar.high
        return [
            Observation(
                self.name,
                bar.ts_close,
                zone.direction,
                refs={"extreme": extreme},
                metrics={
                    "wick_ratio": ratio,
                    "close_pos": close_pos,
                    "range_atr": rng / ctx.atr_m1,
                },
            )
        ]
