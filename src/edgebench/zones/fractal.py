"""Fractal level detector on closed H1 bars (docs/CONTRACT.md section 4.3).

A pivot high needs a high strictly above the ``left`` bars before it and the ``right`` bars after
it; a pivot low is the mirror image. Equal highs or lows are not fractals. The level is known only
when the ``right``-th bar after the pivot closes: using it earlier would be look-ahead. A pivot high
is a BEAR zone (liquidity above), a pivot low a BULL zone (liquidity below).
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from edgebench.config.schema import FractalConfig
from edgebench.contracts import Bar, Direction, Zone, ZoneKind, zone_id
from edgebench.zones.window import BarWindow


class FractalDetector:
    def __init__(self, cfg: FractalConfig, instrument: str) -> None:
        self._cfg = cfg
        self._instrument = instrument
        self._window = BarWindow(cfg.left + cfg.right + 1)
        self._params_hash = hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()[:12]

    def on_bar(self, bar: Bar) -> list[Zone]:
        """Feed one closed H1 bar; return the levels that become known at its close."""
        if not (self._window.push(bar) and self._cfg.enabled):
            return []
        bars = self._window.bars
        left = self._cfg.left
        pivot = bars[left]
        around = bars[:left] + bars[left + 1 :]
        known_at = bars[-1].ts_close
        zones: list[Zone] = []
        if all(pivot.high > other.high for other in around):
            zones.append(self._zone(pivot, Direction.BEAR, pivot.high, known_at))
        if all(pivot.low < other.low for other in around):
            zones.append(self._zone(pivot, Direction.BULL, pivot.low, known_at))
        return zones

    def _zone(self, pivot: Bar, direction: Direction, level: float, known_at: datetime) -> Zone:
        return Zone(
            zone_id=zone_id(self._instrument, ZoneKind.FRACTAL, direction, pivot.ts_close),
            instrument=self._instrument,
            kind=ZoneKind.FRACTAL,
            direction=direction,
            low=level,
            high=level,
            formed_at=pivot.ts_close,
            known_at=known_at,
            extreme_ts=pivot.ts_open,
            params_hash=self._params_hash,
        )
