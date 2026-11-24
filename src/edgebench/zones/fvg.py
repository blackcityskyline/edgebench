"""Fair value gap detector on closed H1 bars (docs/CONTRACT.md section 4.3).

Three consecutive complete bars c1, c2, c3. Bull gap: ``low(c3) > high(c1)``, zone
``[high(c1), low(c3)]``. Bear gap: ``high(c3) < low(c1)``, zone ``[high(c3), low(c1)]``.
The zone is known at the close of c3. During ATR warm-up no zone is emitted, because the size
filter cannot be evaluated yet.
"""

from __future__ import annotations

import hashlib

from edgebench.config.schema import FvgConfig
from edgebench.contracts import Bar, Direction, Zone, ZoneKind, zone_id
from edgebench.zones.atr import WilderATR
from edgebench.zones.window import BarWindow


class FvgDetector:
    def __init__(self, cfg: FvgConfig, instrument: str, atr_period: int = 14) -> None:
        self._cfg = cfg
        self._instrument = instrument
        self._atr = WilderATR(atr_period)
        self._window = BarWindow(3)
        self._params_hash = hashlib.sha256(cfg.model_dump_json().encode()).hexdigest()[:12]

    @property
    def atr(self) -> float | None:
        """ATR (H1) as of the last complete bar."""
        return self._atr.value

    def on_bar(self, bar: Bar) -> list[Zone]:
        """Feed one closed H1 bar; return the zones that become known at its close."""
        atr = self._atr.update(bar) if bar.complete else self._atr.value
        full = self._window.push(bar)
        if not (full and self._cfg.enabled) or atr is None or atr <= 0:
            return []
        c1, c2, c3 = self._window.bars
        if c3.low > c1.high:
            direction, low, high = Direction.BULL, c1.high, c3.low
        elif c3.high < c1.low:
            direction, low, high = Direction.BEAR, c3.high, c1.low
        else:
            return []
        if (high - low) < self._cfg.min_size_atr_h1 * atr:
            return []
        min_body = self._cfg.min_displacement_body_atr_h1
        if min_body is not None and abs(c2.close - c2.open) < min_body * atr:
            return []
        formed = c3.ts_close
        return [
            Zone(
                zone_id=zone_id(self._instrument, ZoneKind.FVG, direction, formed),
                instrument=self._instrument,
                kind=ZoneKind.FVG,
                direction=direction,
                low=low,
                high=high,
                formed_at=formed,
                known_at=formed,
                params_hash=self._params_hash,
            )
        ]
