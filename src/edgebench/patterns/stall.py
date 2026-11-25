"""Stall: price stops moving into the zone. ``n_bars`` quiet bars that make no new extreme."""

from __future__ import annotations

from edgebench.config.schema import StallConfig
from edgebench.contracts import Bar, Direction, Observation
from edgebench.patterns.base import PatternContext


class StallDetector:
    """Fires on the bar that completes the stall, once per stall (edge-triggered).

    The condition at bar ``i``: each of the last ``n_bars`` bars has ``range <= max_range_atr_m1 *
    ATR``, and the extreme of that block does not extend beyond the extreme of the bar just before
    the block by more than ``max_extension_atr_m1 * ATR`` (BULL: lows, BEAR: highs). It must not
    have held at ``i - 1``.
    """

    name = "stall"

    def __init__(self, cfg: StallConfig) -> None:
        self._cfg = cfg

    def reset(self) -> None:
        return None

    def _holds(self, bars: tuple[Bar, ...], ctx: PatternContext) -> bool:
        n = self._cfg.n_bars
        if len(bars) < n + 1:
            return False
        block, prior = bars[-n:], bars[-n - 1]
        if any(b.high - b.low > self._cfg.max_range_atr_m1 * ctx.atr_m1 for b in block):
            return False
        slack = self._cfg.max_extension_atr_m1 * ctx.atr_m1
        if ctx.direction is Direction.BULL:
            return min(b.low for b in block) >= prior.low - slack
        return max(b.high for b in block) <= prior.high + slack

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        bars = ctx.history
        if not self._holds(bars, ctx) or self._holds(bars[:-1], ctx):
            return []
        block = bars[-self._cfg.n_bars :]
        extreme = (
            min(b.low for b in block)
            if ctx.direction is Direction.BULL
            else max(b.high for b in block)
        )
        block_range = max(b.high for b in block) - min(b.low for b in block)
        return [
            Observation(
                self.name,
                bar.ts_close,
                ctx.direction,
                refs={"extreme": extreme},
                metrics={"block_range_atr": block_range / ctx.atr_m1},
            )
        ]
