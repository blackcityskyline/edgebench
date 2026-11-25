"""Sweep: price trades beyond a reference level, then a bar closes back inside."""

from __future__ import annotations

from dataclasses import dataclass

from edgebench.config.schema import SweepConfig
from edgebench.contracts import Bar, Direction, Observation
from edgebench.patterns.base import PatternContext, pivot_levels

_M1_FRACTAL = (2, 2)
_M3_FRACTAL = (2, 2)


@dataclass
class _Pending:
    key: tuple[str, float]
    level: float
    extreme: float
    bars: int = 0


class SweepDetector:
    """Stateful per episode (call ``reset`` between episodes).

    Reference levels for a BULL zone are below price (BEAR mirrored): the zone edge (BULL: zone
    low), the known H1 fractal levels from the context, and unpierced M1/M3 pivot lows. A bar
    that opens at or beyond a level cannot sweep it. A level is *consumed* on its first pierce, so
    it is swept at most once per episode. The pierce must exceed the level by
    ``min_depth_atr_m1 * ATR``. The observation fires on the bar that closes back across the
    level, which may be the piercing bar itself, at most ``max_return_bars - 1`` bars later.
    """

    name = "sweep"

    def __init__(self, cfg: SweepConfig) -> None:
        self._cfg = cfg
        self._pending: list[_Pending] = []
        self._consumed: set[tuple[str, float]] = set()

    def reset(self) -> None:
        self._pending.clear()
        self._consumed.clear()

    def _levels(self, ctx: PatternContext) -> list[tuple[str, float]]:
        bull = ctx.direction is Direction.BULL
        out: list[tuple[str, float]] = []
        for ref in self._cfg.references:
            if ref == "zone_edge":
                out.append((ref, ctx.zone.low if bull else ctx.zone.high))
            elif ref == "h1_fractal":
                out.extend((ref, v) for v in ctx.h1_levels)
            elif ref == "ltf_fractal_m1":
                out.extend(
                    (ref, v) for v in pivot_levels(ctx.history[:-1], ctx.direction, *_M1_FRACTAL)
                )
            elif ref == "ltf_fractal_m3":
                out.extend(
                    (ref, v) for v in pivot_levels(ctx.m3_history, ctx.direction, *_M3_FRACTAL)
                )
        return out

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        bull = ctx.direction is Direction.BULL
        depth_min = self._cfg.min_depth_atr_m1 * ctx.atr_m1
        for key_ref, level in self._levels(ctx):
            key = (key_ref, level)
            if key in self._consumed:
                continue
            opened_inside = bar.open >= level if bull else bar.open <= level
            pierce = level - bar.low if bull else bar.high - level
            if opened_inside and pierce > 0 and pierce >= depth_min:
                self._consumed.add(key)
                self._pending.append(_Pending(key, level, bar.low if bull else bar.high))

        out: list[Observation] = []
        still: list[_Pending] = []
        for p in self._pending:
            p.bars += 1
            p.extreme = min(p.extreme, bar.low) if bull else max(p.extreme, bar.high)
            back = bar.close >= p.level if bull else bar.close <= p.level
            if back:
                depth = (p.level - p.extreme) if bull else (p.extreme - p.level)
                out.append(
                    Observation(
                        self.name,
                        bar.ts_close,
                        ctx.direction,
                        refs={"level": p.level, "extreme": p.extreme},
                        metrics={"depth_atr": depth / ctx.atr_m1, "return_bars": float(p.bars)},
                    )
                )
            elif p.bars < self._cfg.max_return_bars:
                still.append(p)
        self._pending = still
        return out
