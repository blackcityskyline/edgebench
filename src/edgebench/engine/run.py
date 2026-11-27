"""Streaming reference engine (docs/CONTRACT.md section 4.6).

One pass over closed M1 bars. Per bar, in the order of contract 2.1: pending entries fill at this
bar's open and open trades advance; zone lifecycle events are processed; M3/H1 bars completed at
this close are built and H1 zone detectors run; pattern detectors run on active touch episodes; the
strategy turns observations into candidates that fill at the next bar's open. Nothing reads beyond
the current bar, so results cannot depend on future data (tests/test_causality.py).
"""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from edgebench.calendar import session_of
from edgebench.config.environment import SessionsConfig
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import (
    Bar,
    Direction,
    Event,
    Observation,
    OrderIntent,
    Side,
    Trade,
    Zone,
    ZoneEvent,
    ZoneEventType,
    ZoneKind,
    candidate_id,
    event_id,
)
from edgebench.engine.aggregate import Aggregator
from edgebench.execution import CostModel, TradeSim
from edgebench.patterns import PatternContext, PatternSet
from edgebench.zones import FractalDetector, FvgDetector, WilderATR, ZoneBook

MIN = timedelta(minutes=1)
HOUR = timedelta(hours=1)
LOOKBACK_M1 = 60  # closed M1 bars visible to detectors
LOOKBACK_M3 = 30
GAP_RESET = 5 * MIN  # a hole in M1 data longer than this ends episodes and clears the lookback


class UnsupportedConfigError(ValueError):
    """The configuration asks for a feature the engine does not implement yet."""


@dataclass
class RunOutput:
    zones: list[Zone] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    candidates: list[OrderIntent] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class _Episode:
    event_id: str
    zone: Zone
    touch_start_ts: datetime  # close of the touching bar
    touch_bar_open: datetime
    event: Event
    patterns: PatternSet
    observations: list[Observation] = field(default_factory=list)
    seen_triggers: set[str] = field(default_factory=set)
    latest: dict[str, Observation] = field(default_factory=dict)
    all_of_done: bool = False


class Engine:
    def __init__(
        self,
        cfg: StrategyConfig,
        instrument: str,
        costs: CostModel,
        sessions: SessionsConfig,
    ) -> None:
        if cfg.entry.policy != "market_next_open":
            raise UnsupportedConfigError(
                f"entry policy {cfg.entry.policy!r} is not implemented yet"
            )
        self._cfg = cfg
        self._instrument = instrument
        self._costs = costs
        self._sessions = sessions
        self._book = ZoneBook(cfg.zones.fvg, cfg.zones.fractal, cfg.zones.episode_gap_bars)
        self._fvg = FvgDetector(cfg.zones.fvg, instrument)
        self._fractal = FractalDetector(cfg.zones.fractal, instrument)
        self._m3 = Aggregator("M3")
        self._h1 = Aggregator("H1")
        self._atr = WilderATR(14)
        self._m1_hist: deque[Bar] = deque(maxlen=LOOKBACK_M1)
        self._m3_hist: deque[Bar] = deque(maxlen=LOOKBACK_M3)
        self._zones: dict[str, Zone] = {}
        self._episodes: dict[str, _Episode] = {}
        self._episode_log: list[_Episode] = []
        self._pending: list[OrderIntent] = []
        self._sims: list[TradeSim] = []
        self._zone_trades: Counter[str] = Counter()
        self._prev: Bar | None = None
        self.out = RunOutput()
        self._counts: Counter[str] = Counter()
        self._finalized = False

    # -- public --------------------------------------------------------------------------

    def run(self, bars: Iterable[Bar]) -> RunOutput:
        for bar in bars:
            self.on_m1(bar)
        return self.finish()

    def on_m1(self, bar: Bar) -> None:
        """Process one closed M1 bar (decision time = its close)."""
        if bar.tf != "M1":
            raise ValueError("the engine consumes M1 bars")
        if self._prev is not None and bar.ts_open < self._prev.ts_close:
            raise ValueError("M1 bars must be strictly increasing")
        if self._prev is not None and bar.ts_open - self._prev.ts_close > GAP_RESET:
            self._m1_hist.clear()
            self._episodes.clear()
            self._counts["gap_resets"] += 1
        self._fill_and_advance(bar)
        atr_before = self._atr.value
        retired = self._zone_step(bar)
        self._aggregate(bar)
        self._m1_hist.append(bar)
        self._pattern_step(bar, atr_before, retired)
        self._atr.update(bar)
        self._prev = bar
        self._counts["m1_bars"] += 1

    def finish(self) -> RunOutput:
        if not self._finalized:
            for sim in self._sims:
                trade = sim.flush()
                if trade is not None and sim.finished:
                    self.out.trades.append(trade)
            self._sims = []
            self._counts["cancelled_pending"] += len(self._pending)
            self._pending = []
            self.out.events = [
                Event(
                    ep.event.event_id, ep.event.zone_id, ep.event.instrument, ep.event.direction,
                    ep.event.touch_start, ep.event.session, ep.event.features,
                    tuple(ep.observations),
                )
                for ep in self._episode_log
            ]  # fmt: skip
            self.out.counts = dict(self._counts)
            self._finalized = True
        return self.out

    # -- per-bar steps -------------------------------------------------------------------

    def _fill_and_advance(self, bar: Bar) -> None:
        for intent in self._pending:
            if intent.ts_decision != bar.ts_open:
                self._counts["no_fill_gap"] += 1
                continue
            side = intent.side
            try:
                sim = TradeSim(
                    intent.candidate_id, side, intent.stop_price, bar, self._costs,
                    list(self._cfg.exits.ladder_r), self._cfg.exits.reference_r,
                    self._cfg.exits.max_hold_minutes,
                )  # fmt: skip
            except ValueError:
                self._counts["rejected_gap_through_stop"] += 1
                continue
            self._sims.append(sim)
            self._counts["trades_opened"] += 1
        self._pending = []
        still: list[TradeSim] = []
        for sim in self._sims:
            trade = sim.update(bar)
            if trade is not None:
                self.out.trades.append(trade)
            if not sim.finished:
                still.append(sim)
        self._sims = still

    def _zone_step(self, bar: Bar) -> set[str]:
        retired: set[str] = set()
        for ev in self._book.on_m1(bar):
            if ev.type is ZoneEventType.TOUCH_START:
                self._start_episode(ev, bar)
            elif ev.type in (ZoneEventType.INVALIDATED, ZoneEventType.EXPIRED):
                retired.add(ev.zone_id)
        return retired

    def _aggregate(self, bar: Bar) -> None:
        for m3 in self._m3.push(bar):
            if m3.complete:
                self._m3_hist.append(m3)
        for h1 in self._h1.push(bar):
            for zone in [*self._fvg.on_bar(h1), *self._fractal.on_bar(h1)]:
                self._book.add(zone)
                self._zones[zone.zone_id] = zone
                self.out.zones.append(zone)
                self._counts[f"zones_{zone.kind.value.lower()}"] += 1

    def _start_episode(self, ev: ZoneEvent, bar: Bar) -> None:
        zone = self._zones[ev.zone_id]
        assert ev.episode_index is not None
        eid = event_id(zone.zone_id, ev.episode_index)
        atr_h1 = self._fvg.atr
        features: dict[str, float] = {
            "zone_age_h1": (ev.ts - zone.known_at) / HOUR,
            "touch_close": bar.close,
        }
        if atr_h1:
            features["zone_size_atr_h1"] = (zone.high - zone.low) / atr_h1
            dist = self._opposite_distance(zone, bar.close)
            if dist is not None:
                features["dist_opposite_atr_h1"] = dist / atr_h1
        event = Event(
            eid, zone.zone_id, self._instrument, zone.direction, ev.ts,
            session_of(ev.ts, self._sessions), features,
        )  # fmt: skip
        episode = _Episode(
            eid, zone, ev.ts, bar.ts_open, event,
            PatternSet(self._cfg.patterns, self._cfg.zones.window_bars),
        )  # fmt: skip
        self._episodes[eid] = episode
        self._episode_log.append(episode)
        self._counts["events"] += 1

    def _opposite_distance(self, zone: Zone, price: float) -> float | None:
        """Distance from ``price`` to the nearest live zone on the other side (liquidity)."""
        best: float | None = None
        for other in self._book.live_zones():
            if other.direction is zone.direction:
                continue
            d = other.low - price if zone.direction is Direction.BULL else price - other.high
            if d >= 0 and (best is None or d < best):
                best = d
        return best

    def _pattern_step(self, bar: Bar, atr_before: float | None, retired: set[str]) -> None:
        window = self._cfg.zones.window_bars
        for eid, ep in list(self._episodes.items()):
            minutes = int((bar.ts_open - ep.touch_bar_open) / MIN)
            if ep.zone.zone_id in retired or minutes > window:
                del self._episodes[eid]
                continue
            if atr_before is None or atr_before <= 0:
                continue
            levels = tuple(
                z.low
                for z in self._book.live_zones()
                if z.kind is ZoneKind.FRACTAL and z.direction is ep.zone.direction
            )
            ctx = PatternContext(
                zone=ep.zone,
                episode_index=int(eid.rsplit("#", 1)[1]),
                touch_start=ep.touch_start_ts,
                atr_m1=atr_before,
                history=tuple(self._m1_hist),
                m3_history=tuple(self._m3_hist),
                h1_levels=levels,
                bars_since_touch=minutes,
            )
            for obs in ep.patterns.on_bar(bar, ctx):
                ep.observations.append(obs)
                ep.latest[obs.detector] = obs
                self._decide(ep, obs, bar, atr_before)

    # -- strategy ------------------------------------------------------------------------

    def _decide(self, ep: _Episode, obs: Observation, bar: Bar, atr: float) -> None:
        cfg = self._cfg
        if obs.detector not in cfg.entry.triggers:
            return
        if session_of(bar.ts_close, self._sessions) not in cfg.sessions:
            self._counts["skip_session"] += 1
            return
        if cfg.mode == "portfolio":
            self._decide_portfolio(ep, obs, bar, atr)
        elif obs.detector not in ep.seen_triggers:
            self._propose(ep, obs.detector, [obs], bar, atr)

    def _decide_portfolio(self, ep: _Episode, obs: Observation, bar: Bar, atr: float) -> None:
        cfg = self._cfg
        if cfg.entry.combine == "all_of":
            if ep.all_of_done or not set(cfg.entry.triggers) <= set(ep.latest):
                return
            trigger, used = "all_of", [ep.latest[t] for t in cfg.entry.triggers]
        else:
            if ep.seen_triggers:  # "first": only one candidate per event
                return
            trigger, used = obs.detector, [obs]
        if self._zone_trades[ep.zone.zone_id] >= cfg.entry.max_trades_per_zone:
            self._counts["skip_zone_limit"] += 1
            return
        if self._pending or any(not s.position_closed for s in self._sims):
            self._counts["skip_position_open"] += 1
            return
        if self._propose(ep, trigger, used, bar, atr) and trigger == "all_of":
            ep.all_of_done = True

    def _propose(
        self, ep: _Episode, trigger: str, used: list[Observation], bar: Bar, atr: float
    ) -> bool:
        cfg, costs = self._cfg, self._costs
        long = used[0].direction is Direction.BULL
        extremes = [self._extreme(o, long) for o in used]
        buffer = (
            cfg.entry.stop_buffer.spreads * costs.filter_spread + cfg.entry.stop_buffer.atr_m1 * atr
        )
        entry_ref = bar.close
        stop = min(extremes) - buffer if long else max(extremes) + buffer
        distance = entry_ref - stop if long else stop - entry_ref
        atr_h1 = self._fvg.atr
        if distance <= 0:
            self._counts["skip_price_beyond_stop"] += 1
            return False
        if distance < cfg.entry.min_stop_spreads * costs.filter_spread:
            self._counts["skip_stop_too_tight"] += 1
            return False
        if not atr_h1 or distance > cfg.entry.max_stop_atr_h1 * atr_h1:
            self._counts["skip_stop_too_wide"] += 1
            return False
        intent = OrderIntent(
            candidate_id(ep.event_id, trigger), ep.event_id, trigger, bar.ts_close,
            Side.LONG if long else Side.SHORT, cfg.entry.policy, entry_ref, stop,
        )  # fmt: skip
        ep.seen_triggers.add(trigger)
        self._zone_trades[ep.zone.zone_id] += 1
        self.out.candidates.append(intent)
        self._pending.append(intent)
        self._counts["candidates"] += 1
        return True

    @staticmethod
    def _extreme(obs: Observation, long: bool) -> float:
        if "extreme" in obs.refs:
            return obs.refs["extreme"]
        return obs.refs["mother_low"] if long else obs.refs["mother_high"]


def run_engine(
    cfg: StrategyConfig,
    instrument: str,
    bars: Iterable[Bar],
    costs: CostModel,
    sessions: SessionsConfig,
) -> RunOutput:
    """Run one instrument through the streaming engine."""
    engine = Engine(cfg, instrument, costs, sessions)
    return engine.run(bars)
