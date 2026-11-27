"""Engine on a hand-built scenario: bull H1 FVG, M1 descent into it, a rejection bar, a rally."""

from datetime import UTC, datetime, timedelta

import pytest

from edgebench.config.environment import SessionsConfig
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import Bar, Direction, ExitReason, Side, ZoneKind
from edgebench.engine import Engine, UnsupportedConfigError, run_engine
from edgebench.execution import CostModel

START = datetime(2024, 1, 2, 0, 0, tzinfo=UTC)  # 19:00 New York, inside the "all" session
MIN = timedelta(minutes=1)
COSTS = CostModel(spread=0.02, slippage=0.01)
SESSIONS = SessionsConfig.model_validate(
    {"tz": "America/New_York", "sessions": {"all": {"start": "00:00", "end": "23:59"}}}
)
Row = tuple[float, float, float, float]


def hour(o: float, h: float, lo: float, c: float) -> list[Row]:
    """60 M1 bars whose union is the given H1 bar (extremes on minutes 10 and 20)."""
    rows: list[Row] = []
    for k in range(60):
        a = o + (c - o) * k / 60
        b = o + (c - o) * (k + 1) / 60
        hi, lo_ = max(a, b) + 0.001, min(a, b) - 0.001
        if k == 10:
            hi = h
        if k == 20:
            lo_ = lo
        rows.append((a, hi, lo_, b))
    rows[0] = (o, rows[0][1], rows[0][2], rows[0][3])
    rows[-1] = (rows[-1][0], rows[-1][1], rows[-1][2], c)
    return rows


def scenario() -> tuple[list[Row], int, int]:
    """Returns M1 rows, the index of the rejection bar and the index of the fill bar."""
    rows: list[Row] = []
    for _ in range(16):  # warm-up: ATR(H1) is about 1.0
        rows += hour(100.0, 100.5, 99.5, 100.0)
    rows += hour(100.0, 100.5, 99.5, 100.2)  # c1, high 100.5
    rows += hour(100.2, 103.0, 100.1, 102.9)  # c2
    rows += hour(102.9, 103.5, 102.0, 103.2)  # c3, low 102.0: bull FVG [100.5, 102.0]
    for _ in range(3):
        rows += hour(103.2, 103.6, 103.0, 103.3)  # stay above the zone
    quiet: Row = (103.3, 103.35, 103.25, 103.3)
    hour7 = [quiet] * 40
    for k in range(10):  # descent to 102.3, lows stay above the zone high (102.0)
        o = 103.3 - 0.1 * k
        hour7.append((o, o + 0.02, o - 0.12, o - 0.1))
    hour7.append((102.3, 102.4, 101.8, 102.35))  # rejection bar, minute 50
    hour7.append((102.35, 102.6, 102.3, 102.55))  # fill bar
    for k in range(8):
        o = 102.55 + 0.1 * k
        hour7.append((o, o + 0.11, o - 0.01, o + 0.1))
    assert len(hour7) == 60
    rows += hour7
    p = 103.35
    for _ in range(300):  # rally
        rows.append((p, p + 0.11, p - 0.01, p + 0.1))
        p += 0.1
    start_of_hour7 = (16 + 3 + 3) * 60
    return rows, start_of_hour7 + 50, start_of_hour7 + 51


def to_bars(rows: list[Row], start: datetime = START) -> list[Bar]:
    return [Bar(start + i * MIN, o, h, lo, c, 1.0, "M1") for i, (o, h, lo, c) in enumerate(rows)]


def config(**overrides: object) -> StrategyConfig:
    base: dict[str, object] = {
        "instruments": ["EURUSD"],
        "sessions": ["all"],
        "zones": {"fractal": {"enabled": False}},
        "patterns": {
            "sweep": {"enabled": False},
            "stall": {"enabled": False},
            "inside": {"enabled": False},
        },
        "entry": {"triggers": ["rejection"], "max_stop_atr_h1": 2.0},
    }
    base.update(overrides)
    return StrategyConfig.model_validate(base)


def test_fvg_is_known_at_the_close_of_its_third_bar() -> None:
    rows, rej, _ = scenario()
    out = run_engine(config(), "EURUSD", to_bars(rows), COSTS, SESSIONS)
    fvgs = [z for z in out.zones if z.kind is ZoneKind.FVG]
    zone = fvgs[0]  # the rally creates more FVGs later, all above the price
    assert zone.direction is Direction.BULL
    assert (zone.low, zone.high) == (100.5, 102.0)
    assert zone.known_at == START + 19 * 60 * MIN
    assert out.events[0].touch_start == START + (rej + 1) * MIN > zone.known_at


def test_rejection_bar_creates_one_candidate_that_fills_on_the_next_open() -> None:
    rows, rej, fill = scenario()
    out = run_engine(config(), "EURUSD", to_bars(rows), COSTS, SESSIONS)
    assert len(out.events) == 1 and len(out.candidates) == 1 and len(out.trades) == 1
    event, cand, trade = out.events[0], out.candidates[0], out.trades[0]
    assert event.zone_id.startswith("EURUSD:FVG:BULL:") and event.event_id.endswith("#0")
    assert [o.detector for o in event.observations] == ["rejection"]
    assert event.session == "all"
    assert cand.candidate_id == f"{event.event_id}:rejection" and cand.side is Side.LONG
    assert cand.ts_decision == START + (rej + 1) * MIN
    assert cand.entry_ref == 102.35
    assert cand.stop_price == pytest.approx(101.8 - 0.02)  # rejection low minus one spread
    assert trade.trade_id == cand.candidate_id
    assert trade.entry_ts == START + fill * MIN  # no same-bar fill
    assert trade.entry_fill == pytest.approx(102.35 + 0.02)  # ask = next bid open + spread
    risk = trade.entry_fill - cand.stop_price
    assert trade.risk_distance == pytest.approx(risk)
    # oracle: first bar whose high reaches each rung, scanning forward from the entry bar
    bars = to_bars(rows)
    for rung in ("1", "2", "3", "5"):
        target = trade.entry_fill + float(rung) * risk
        first = next(b for b in bars[fill:] if b.high >= target)
        assert trade.ladder[rung] == first.ts_close
    assert trade.ladder["stop"] is None
    assert trade.exit_reason is ExitReason.TARGET and trade.exit_ts == trade.ladder["2"]
    assert trade.r_net == pytest.approx(2.0)
    assert out.counts["candidates"] == 1 and out.counts["events"] == 1


def test_filters_are_counted_and_the_event_row_is_kept() -> None:
    rows, _, _ = scenario()
    wide = config(entry={"triggers": ["rejection"], "max_stop_atr_h1": 0.1})
    out = run_engine(wide, "EURUSD", to_bars(rows), COSTS, SESSIONS)
    assert (len(out.events), len(out.candidates)) == (1, 0)
    assert out.counts["skip_stop_too_wide"] == 1
    tight = config(
        entry={"triggers": ["rejection"], "max_stop_atr_h1": 2.0, "min_stop_spreads": 50}
    )
    out = run_engine(tight, "EURUSD", to_bars(rows), COSTS, SESSIONS)
    assert out.counts["skip_stop_too_tight"] == 1 and out.candidates == []
    elsewhere = SessionsConfig.model_validate(
        {"sessions": {"all": {"start": "09:30", "end": "10:00"}}}
    )
    out = run_engine(config(), "EURUSD", to_bars(rows), COSTS, elsewhere)
    assert out.counts["skip_session"] == 1 and out.candidates == []


def test_unsupported_entry_policy_is_refused_loudly() -> None:
    cfg = config(entry={"triggers": ["rejection"], "policy": "limit_retrace"})
    with pytest.raises(UnsupportedConfigError):
        Engine(cfg, "EURUSD", COSTS, SESSIONS)


def test_portfolio_mode_limits_candidates_per_zone_and_per_position() -> None:
    rows, _, _ = scenario()
    cfg = config(mode="portfolio")
    out = run_engine(cfg, "EURUSD", to_bars(rows), COSTS, SESSIONS)
    assert len(out.candidates) == 1 and len(out.trades) == 1


def test_a_data_hole_ends_the_episode_and_cancels_the_pending_entry() -> None:
    rows, rej, _ = scenario()
    bars = to_bars(rows)
    # remove the fill bar and everything for 30 minutes: the entry cannot fill on "the next bar"
    holed = bars[: rej + 1] + bars[rej + 31 :]
    out = run_engine(config(), "EURUSD", holed, COSTS, SESSIONS)
    assert len(out.candidates) == 1 and out.trades == []
    assert out.counts["no_fill_gap"] == 1 and out.counts["gap_resets"] == 1


def test_bars_must_be_increasing_and_m1() -> None:
    rows, _, _ = scenario()
    bars = to_bars(rows)
    eng = Engine(config(), "EURUSD", COSTS, SESSIONS)
    eng.on_m1(bars[5])
    with pytest.raises(ValueError, match="increasing"):
        eng.on_m1(bars[4])
    with pytest.raises(ValueError, match="M1"):
        eng.on_m1(Bar(START, 1, 1, 1, 1, 0, "H1"))


def test_cost_multiplier_changes_results_but_not_which_candidates_exist() -> None:
    rows, _, _ = scenario()
    bars = to_bars(rows)
    spec_costs = CostModel(0.02, 0.01, 0.0, nominal_spread=0.02)
    doubled = CostModel(0.04, 0.02, 0.0, nominal_spread=0.02)
    base = run_engine(config(), "EURUSD", bars, spec_costs, SESSIONS)
    more = run_engine(config(), "EURUSD", bars, doubled, SESSIONS)
    assert [c.candidate_id for c in more.candidates] == [c.candidate_id for c in base.candidates]
    assert [c.stop_price for c in more.candidates] == [c.stop_price for c in base.candidates]
    assert more.trades[0].entry_fill > base.trades[0].entry_fill
