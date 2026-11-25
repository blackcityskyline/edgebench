"""M1 pattern detectors that run while a zone touch episode is active (contract section 4.4)."""

from __future__ import annotations

from edgebench.config.schema import PatternsConfig
from edgebench.contracts import Bar, Observation
from edgebench.patterns.base import PatternContext, PatternDetector, pivot_levels
from edgebench.patterns.inside import InsideDetector
from edgebench.patterns.rejection import RejectionDetector
from edgebench.patterns.stall import StallDetector
from edgebench.patterns.sweep import SweepDetector


class PatternSet:
    """The enabled detectors of one configuration, run together for one episode stream."""

    def __init__(self, cfg: PatternsConfig, window_bars: int) -> None:
        self._window = window_bars
        self._detectors: list[PatternDetector] = []
        if cfg.sweep.enabled:
            self._detectors.append(SweepDetector(cfg.sweep))
        if cfg.stall.enabled:
            self._detectors.append(StallDetector(cfg.stall))
        if cfg.rejection.enabled:
            self._detectors.append(RejectionDetector(cfg.rejection))
        if cfg.inside.enabled:
            self._detectors.append(InsideDetector(cfg.inside))

    @property
    def names(self) -> list[str]:
        return [d.name for d in self._detectors]

    def reset(self) -> None:
        for d in self._detectors:
            d.reset()

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        """Observations completed by ``bar``; nothing once the episode window has passed."""
        if ctx.bars_since_touch > self._window:
            return []
        return [obs for d in self._detectors for obs in d.on_bar(bar, ctx)]


__all__ = [
    "InsideDetector",
    "PatternContext",
    "PatternDetector",
    "PatternSet",
    "RejectionDetector",
    "StallDetector",
    "SweepDetector",
    "pivot_levels",
]
