"""Pattern-free control trigger (docs/CONTRACT.md section 7.3).

At each bar inside the episode window the detector fires with probability ``probability``, using a
hash of (seed, zone, episode, bar time) instead of a random generator, so it is deterministic and
independent of call order. Its stop is the extreme of the firing bar, like rejection, so comparing
the two isolates what the pattern itself adds over "any bar at the zone".
"""

from __future__ import annotations

import hashlib

from edgebench.config.schema import BaselineConfig
from edgebench.contracts import Bar, Direction, Observation
from edgebench.patterns.base import PatternContext


class BaselineDetector:
    name = "baseline"

    def __init__(self, cfg: BaselineConfig) -> None:
        self._cfg = cfg

    def reset(self) -> None:
        return None

    def _draw(self, bar: Bar, ctx: PatternContext) -> float:
        key = f"{self._cfg.seed}|{ctx.zone.zone_id}|{ctx.episode_index}|{bar.ts_open.isoformat()}"
        digest = hashlib.sha256(key.encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        if self._draw(bar, ctx) >= self._cfg.probability:
            return []
        extreme = bar.low if ctx.direction is Direction.BULL else bar.high
        return [Observation(self.name, bar.ts_close, ctx.direction, refs={"extreme": extreme})]


class MirrorDetector(BaselineDetector):
    """The baseline's bars with the opposite direction (and the stop on the other side).

    If the zone context carries an edge, the mirror should lose about as much as the baseline wins;
    if both win, the gain comes from the data or the engine, not from the zone.
    """

    name = "mirror"

    def on_bar(self, bar: Bar, ctx: PatternContext) -> list[Observation]:
        if self._draw(bar, ctx) >= self._cfg.probability:
            return []
        bull = ctx.direction is Direction.BULL
        flipped = Direction.BEAR if bull else Direction.BULL
        extreme = bar.high if bull else bar.low
        return [Observation(self.name, bar.ts_close, flipped, refs={"extreme": extreme})]
