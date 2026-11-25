"""G4: the engine's output up to time T must not depend on any bar after T.

Method: run the full series once. Then, for several cut points, (a) run on the truncated series and
(b) run on the series whose future part was rescaled up and down. Everything the engine had decided
by the cut (zones known, events started, observations made, candidates created) must be identical
to the full run's. Trade results are compared only where they are final before the cut.
"""

from dataclasses import replace
from datetime import datetime

import pytest

from edgebench.config.environment import SessionsConfig
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import Bar, ExitReason
from edgebench.data.synthetic import make_m1
from edgebench.engine import RunOutput, run_engine
from edgebench.execution import CostModel

pytestmark = pytest.mark.slow

COSTS = CostModel(spread=0.01, slippage=0.005)
SESSIONS = SessionsConfig.model_validate(
    {"tz": "America/New_York", "sessions": {"all": {"start": "00:00", "end": "23:59"}}}
)
CUTS = [4_000, 9_001, 14_500, 21_333]


def make_bars(n: int = 26_000) -> list[Bar]:
    frame = make_m1(n, seed=11, vol_bp=8.0)
    return [
        Bar(r.ts_open, r.open, r.high, r.low, r.close, r.volume, "M1")
        for r in frame.itertuples(index=False)
    ]


def config() -> StrategyConfig:
    return StrategyConfig.model_validate(
        {
            "instruments": ["EURUSD"],
            "sessions": ["all"],
            "zones": {"episode_gap_bars": 3},
            "entry": {"max_stop_atr_h1": 3.0, "min_stop_spreads": 1.0},
        }
    )


def run(bars: list[Bar]) -> RunOutput:
    return run_engine(config(), "EURUSD", bars, COSTS, SESSIONS)


def decided_by(out: RunOutput, cut: datetime) -> dict[str, object]:
    events = {
        e.event_id: (
            e.zone_id,
            e.touch_start,
            e.session,
            e.features,
            tuple(o for o in e.observations if o.ts_decision <= cut),
        )
        for e in out.events
        if e.touch_start <= cut
    }
    return {
        "zones": [z for z in out.zones if z.known_at <= cut],
        "events": events,
        "candidates": [c for c in out.candidates if c.ts_decision <= cut],
    }


def final_trades(out: RunOutput, cut: datetime) -> dict[str, tuple[object, ...]]:
    return {
        t.trade_id: (t.entry_ts, t.entry_fill, t.exit_ts, t.exit_reason, t.r_net)
        for t in out.trades
        if t.exit_reason in (ExitReason.STOP, ExitReason.TARGET) and t.exit_ts <= cut
    }


def scaled(bars: list[Bar], from_index: int, factor: float) -> list[Bar]:
    return bars[:from_index] + [
        replace(
            b,
            open=b.open * factor,
            high=b.high * factor,
            low=b.low * factor,
            close=b.close * factor,
        )
        for b in bars[from_index:]
    ]


@pytest.fixture(scope="module")
def bars() -> list[Bar]:
    return make_bars()


@pytest.fixture(scope="module")
def full(bars: list[Bar]) -> RunOutput:
    return run(bars)


def test_the_scenario_is_rich_enough_to_mean_something(full: RunOutput) -> None:
    assert len(full.zones) > 50 and len(full.events) > 20
    assert len(full.candidates) > 20 and len(full.trades) > 20
    assert {o.detector for e in full.events for o in e.observations} >= {"rejection", "stall"}


@pytest.mark.parametrize("cut_index", CUTS)
def test_truncating_the_future_changes_nothing_decided(
    bars: list[Bar], full: RunOutput, cut_index: int
) -> None:
    cut = bars[cut_index - 1].ts_close
    short = run(bars[:cut_index])
    assert decided_by(short, cut) == decided_by(full, cut)
    assert final_trades(short, cut) == final_trades(full, cut)
    assert decided_by(short, cut)["candidates"], "the prefix must contain decisions"


@pytest.mark.parametrize("factor", [0.93, 1.07])
@pytest.mark.parametrize("cut_index", CUTS)
def test_perturbing_the_future_changes_nothing_decided(
    bars: list[Bar], full: RunOutput, cut_index: int, factor: float
) -> None:
    cut = bars[cut_index - 1].ts_close
    changed = run(scaled(bars, cut_index, factor))
    assert decided_by(changed, cut) == decided_by(full, cut)
    assert final_trades(changed, cut) == final_trades(full, cut)
