"""Zone lifecycle and touch episodes on M1 bars (docs/CONTRACT.md section 4.3).

``add`` registers a zone once it is known; ``on_m1`` then advances every live zone by one closed M1
bar and returns lifecycle events stamped with that bar's close. Rules, in the order applied to each
bar and zone:

1. A bar can touch a zone only if ``bar.ts_open >= zone.known_at`` (no look-ahead).
2. Expiry: a zone older than its ``max_age_h1_bars`` (measured from ``known_at``) is retired.
3. A *touch* is an M1 bar whose range overlaps the zone (a fractal level: the range reaches it).
   An *episode* starts at the first touching bar and ends after ``episode_gap_bars`` consecutive
   bars that do not touch. After ``max_episodes`` episodes the zone is MITIGATED.
4. Invalidation (decision D2), checked on every bar even without a touch, for a BULL zone (support)
   with BEAR mirrored: ``close_through`` a close below the zone low; ``full_fill`` a bar whose low
   reaches the zone low; ``first_touch`` the zone is spent as soon as its first episode ends;
   ``never`` no invalidation. A wick through the zone that closes back inside it is a sweep, not an
   invalidation, under the default ``close_through``.

When a zone is retired while an episode is active, TOUCH_END is emitted first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from edgebench.config.schema import FractalConfig, FvgConfig
from edgebench.contracts import Bar, Direction, Zone, ZoneEvent, ZoneEventType, ZoneKind


@dataclass
class _State:
    zone: Zone
    invalid_on: str
    max_episodes: int
    max_age: timedelta
    episodes_done: int = 0
    active: bool = False
    outside_bars: int = 0


class ZoneBook:
    def __init__(self, fvg: FvgConfig, fractal: FractalConfig, episode_gap_bars: int) -> None:
        if episode_gap_bars < 1:
            raise ValueError("episode_gap_bars must be >= 1")
        self._fvg = fvg
        self._fractal = fractal
        self._gap = episode_gap_bars
        self._states: dict[str, _State] = {}

    def add(self, zone: Zone) -> None:
        """Register a zone that has become known. Duplicates are rejected."""
        if zone.zone_id in self._states:
            raise ValueError(f"zone {zone.zone_id} is already tracked")
        cfg = self._fvg if zone.kind is ZoneKind.FVG else self._fractal
        self._states[zone.zone_id] = _State(
            zone=zone,
            invalid_on=cfg.invalid_on,
            max_episodes=cfg.max_episodes,
            max_age=timedelta(hours=cfg.max_age_h1_bars),
        )

    def live_zones(self) -> list[Zone]:
        return [state.zone for state in self._states.values()]

    def active_episode(self, zone_id: str) -> int | None:
        """Index of the zone's running touch episode, or None."""
        state = self._states.get(zone_id)
        return state.episodes_done if state is not None and state.active else None

    def on_m1(self, bar: Bar) -> list[ZoneEvent]:
        """Advance all live zones by one closed M1 bar."""
        if bar.tf != "M1":
            raise ValueError(f"ZoneBook needs M1 bars, got {bar.tf}")
        events: list[ZoneEvent] = []
        for zone_id in list(self._states):
            state = self._states[zone_id]
            if bar.ts_open < state.zone.known_at:
                continue
            retired = self._step(state, bar, events)
            if retired:
                del self._states[zone_id]
        return events

    # -- internals -----------------------------------------------------------------------

    def _step(self, state: _State, bar: Bar, events: list[ZoneEvent]) -> bool:
        zone, ts = state.zone, bar.ts_close

        def emit(kind: ZoneEventType, episode: int | None = None) -> None:
            events.append(ZoneEvent(zone.zone_id, ts, kind, episode))

        def end_episode() -> None:
            if state.active:
                emit(ZoneEventType.TOUCH_END, state.episodes_done)
                state.active = False
                state.episodes_done += 1

        if ts - zone.known_at >= state.max_age:
            end_episode()
            emit(ZoneEventType.EXPIRED)
            return True

        touching = bar.low <= zone.high and bar.high >= zone.low
        if touching:
            state.outside_bars = 0
            if not state.active and state.episodes_done < state.max_episodes:
                state.active = True
                emit(ZoneEventType.TOUCH_START, state.episodes_done)
        elif state.active:
            state.outside_bars += 1
            if state.outside_bars >= self._gap:
                end_episode()
                state.outside_bars = 0

        if self._invalidated(state, bar):
            end_episode()
            emit(ZoneEventType.INVALIDATED)
            return True
        if state.episodes_done >= state.max_episodes and not state.active:
            emit(ZoneEventType.MITIGATED)
            return True
        return False

    @staticmethod
    def _invalidated(state: _State, bar: Bar) -> bool:
        zone, mode = state.zone, state.invalid_on
        if mode == "never":
            return False
        if mode == "first_touch":
            return state.episodes_done >= 1 and not state.active
        if mode == "close_through":
            if zone.direction is Direction.BULL:
                return bar.close < zone.low
            return bar.close > zone.high
        if mode == "full_fill":
            if zone.direction is Direction.BULL:
                return bar.low <= zone.low
            return bar.high >= zone.high
        raise ValueError(f"unknown invalid_on {mode!r}")
