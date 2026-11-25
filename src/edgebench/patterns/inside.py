"""Inside-like stall (harami-style): a bar contained in the previous bar."""

from __future__ import annotations

from edgebench.config.schema import InsideConfig
from edgebench.contracts import Bar, Observation
from edgebench.patterns.base import PatternContext


def _span(bar: Bar, mode: str) -> tuple[float, float]:
    if mode == "body":
        return min(bar.open, bar.close), max(bar.open, bar.close)
    return bar.low, bar.high


class InsideDetector:
    """Fires when ``min_count`` consecutive bars are each inside the one before (edge-triggered).

    ``mode`` selects the range (high-low) or the body (open-close) as the contained span. Equal
    edges count as inside.
    """

    name = "inside"

    def __init__(self, cfg: InsideConfig) -> None:
        self._cfg = cfg

    def reset(self) -> None:
        return None

    def _run_length(self, bars: tuple[Bar, ...]) -> int:
        count = 0
        for i in range(len(bars) - 1, 0, -1):
            lo, hi = _span(bars[i], self._cfg.mode)
            plo, phi = _span(bars[i - 1], self._cfg.mode)
            if lo >= plo and hi <= phi:
                count += 1
            else:
                break
        return count

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        if self._run_length(ctx.history) != self._cfg.min_count:
            return []
        mother = ctx.history[-self._cfg.min_count - 1]
        lo, hi = _span(bar, self._cfg.mode)
        plo, phi = _span(mother, self._cfg.mode)
        return [
            Observation(
                self.name,
                bar.ts_close,
                ctx.direction,
                refs={"mother_high": mother.high, "mother_low": mother.low},
                metrics={"size_ratio": (hi - lo) / (phi - plo) if phi > plo else 0.0},
            )
        ]
