"""Fills and trade simulation with hand-computed answers.

Long: costs spread 0.2, stop slippage 0.1. Entry bar open 100 -> fill 100.2, stop 99.2, risk 1.0,
rungs 1R/2R/3R = 101.2/102.2/103.2, reference exit 2R.
"""

from datetime import UTC, datetime, timedelta

import pytest

from edgebench.config.environment import InstrumentSpec
from edgebench.contracts import Bar, ExitReason, Side, Trade
from edgebench.execution import CostModel, TradeSim, fills, rung_key

T0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
COSTS = CostModel(spread=0.2, slippage=0.1)


def bar(i: int, o: float, h: float, lo: float, c: float) -> Bar:
    return Bar(T0 + i * MIN, o, h, lo, c, 1.0, "M1")


def sim(
    side: Side = Side.LONG,
    stop: float = 99.2,
    costs: CostModel = COSTS,
    max_hold: int = 60,
    entry: Bar | None = None,
) -> TradeSim:
    return TradeSim(
        "t", side, stop, entry or bar(0, 100.0, 100.5, 99.5, 100.3), costs, [1, 2, 3], 2, max_hold
    )


def test_cost_model_from_spec_and_validation() -> None:
    spec = InstrumentSpec(
        source="binance", symbol="BTCUSDT", tick_size=0.01, spread=0.1,
        slippage_spreads=0.5, commission_bps=10,
    )  # fmt: skip
    assert CostModel.from_spec(spec) == CostModel(0.1, 0.05, 10, 0.1)
    doubled = CostModel.from_spec(spec, 2.0)
    assert (doubled.spread, doubled.slippage, doubled.commission_bps) == (0.2, 0.1, 20)
    assert doubled.filter_spread == 0.1 and CostModel(0.3).filter_spread == 0.3
    with pytest.raises(ValueError):
        CostModel(-1.0)


@pytest.mark.parametrize(
    ("side", "bar_row", "stop_hit", "fill"),
    [
        (Side.LONG, (100.0, 100.5, 99.3, 100.0), False, None),
        (Side.LONG, (100.0, 100.5, 99.2, 100.0), True, 99.1),  # low == stop triggers
        (Side.LONG, (98.0, 98.5, 97.9, 98.2), True, 97.9),  # gap: filled at the open, not the stop
        (Side.SHORT, (100.0, 100.7, 99.5, 100.0), False, None),  # 100.7 + 0.2 < 101
        (Side.SHORT, (100.0, 100.8, 99.5, 100.0), True, 101.1),  # ask high reaches 101
        (Side.SHORT, (102.0, 102.5, 101.9, 102.0), True, 102.3),  # gap: ask open + slippage
    ],
)
def test_stop_table(
    side: Side, bar_row: tuple[float, float, float, float], stop_hit: bool, fill: float | None
) -> None:
    stop = 99.2 if side is Side.LONG else 101.0
    b = bar(1, *bar_row)
    assert fills.stop_triggered(side, b, stop, COSTS) is stop_hit
    if stop_hit:
        assert fills.stop_fill(side, b, stop, COSTS) == pytest.approx(fill)


def test_entry_and_target_and_timeout_table() -> None:
    assert fills.entry_fill(Side.LONG, 100.0, COSTS) == pytest.approx(100.2)
    assert fills.entry_fill(Side.SHORT, 100.0, COSTS) == 100.0
    assert fills.target_price(Side.LONG, 100.2, 1.0, 2) == pytest.approx(102.2)
    assert fills.target_price(Side.SHORT, 100.0, 1.0, 2) == 98.0
    assert fills.target_triggered(Side.LONG, bar(1, 100, 102.2, 100, 101), 102.2, COSTS)
    assert not fills.target_triggered(Side.LONG, bar(1, 100, 102.1, 100, 101), 102.2, COSTS)
    assert fills.target_triggered(Side.SHORT, bar(1, 100, 100, 97.8, 99), 98.0, COSTS)
    assert not fills.target_triggered(Side.SHORT, bar(1, 100, 100, 97.9, 99), 98.0, COSTS)
    assert fills.timeout_fill(Side.LONG, 100.4, COSTS) == 100.4
    assert fills.timeout_fill(Side.SHORT, 100.4, COSTS) == pytest.approx(100.6)
    assert fills.commission_r(100.2, 1.0, CostModel(0.2, 0.1, 10)) == pytest.approx(0.2004)


def test_long_target_reached_before_the_stop() -> None:
    s = sim()
    assert s.entry_fill == pytest.approx(100.2) and s.risk == pytest.approx(1.0)
    assert s.update(bar(0, 100.0, 100.5, 99.5, 100.3)) is None  # the entry bar is evaluated too
    assert s.update(bar(1, 100.3, 101.5, 100.0, 101.0)) is None  # rung 1
    assert s.update(bar(2, 101.0, 102.5, 100.9, 102.0)) is None  # rung 2: frees the position
    assert s.position_closed and s.reference_exit_ts == T0 + 3 * MIN
    trade = s.update(bar(3, 102.0, 103.5, 101.8, 103.0))  # rung 3: ladder complete
    assert trade is not None and s.finished
    assert trade.exit_reason is ExitReason.TARGET
    assert trade.exit_ts == T0 + 3 * MIN and trade.exit_fill == pytest.approx(102.2)
    assert trade.r_net == pytest.approx(2.0)
    assert trade.mfe_r == pytest.approx(3.3) and trade.mae_r == pytest.approx(0.7)
    assert trade.ladder == {
        "stop": None,
        "1": T0 + 2 * MIN,
        "2": T0 + 3 * MIN,
        "3": T0 + 4 * MIN,
    }
    assert trade.entry_ts == T0 and trade.ambiguous_bars == 0
    assert s.update(bar(4, 1, 1, 1, 1)) is trade  # finished simulations ignore later bars


def test_long_stop_with_slippage_and_cost() -> None:
    s = sim()
    s.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    trade = s.update(bar(1, 100.0, 100.2, 99.0, 99.4))
    assert trade is not None and trade.exit_reason is ExitReason.STOP
    assert trade.exit_fill == pytest.approx(99.1) and trade.r_net == pytest.approx(-1.1)
    assert trade.cost_r == pytest.approx(0.3)  # spread 0.2 + stop slippage 0.1, in R
    assert trade.ladder["stop"] == T0 + 2 * MIN
    assert s.position_closed


def test_a_bar_that_hits_the_stop_and_a_rung_counts_for_the_stop() -> None:
    s = sim()
    trade = s.update(bar(0, 100.0, 101.5, 99.0, 100.0))  # entry bar: rung 1 and the stop
    assert trade is not None and trade.exit_reason is ExitReason.STOP
    assert trade.ambiguous_bars == 1 and trade.ladder["1"] is None


def test_rung_before_the_stop_does_not_make_the_reference_exit_a_target() -> None:
    s = sim()
    s.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    s.update(bar(1, 100.3, 101.5, 100.0, 101.0))  # rung 1 only
    trade = s.update(bar(2, 100.5, 100.6, 99.0, 99.1))
    assert trade is not None and trade.exit_reason is ExitReason.STOP
    assert trade.ladder["1"] == T0 + 2 * MIN and trade.ladder["stop"] == T0 + 3 * MIN
    assert trade.mfe_r == pytest.approx(1.3)


def test_timeout_exits_at_the_close_of_the_last_bar_inside_the_limit() -> None:
    s = sim(max_hold=3)
    for i, close in enumerate([100.3, 100.1, 100.4]):
        assert s.update(bar(i, 100.2, 100.6, 99.8, close)) is None
    trade = s.update(bar(3, 100.4, 100.5, 100.3, 100.4))  # opens at the deadline: not evaluated
    assert trade is not None and trade.exit_reason is ExitReason.TIMEOUT
    assert trade.exit_ts == T0 + 3 * MIN and trade.exit_fill == pytest.approx(100.4)
    assert trade.r_net == pytest.approx(0.2)


def test_flush_closes_at_the_last_seen_bar() -> None:
    s = sim()
    s.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    trade = s.flush()
    assert trade is not None and trade.exit_reason is ExitReason.TIMEOUT
    assert trade.exit_fill == pytest.approx(100.3)


def test_short_target_and_stop() -> None:
    entry = bar(0, 100.0, 100.4, 99.6, 100.0)
    s = sim(Side.SHORT, stop=101.0, entry=entry)
    assert s.entry_fill == 100.0 and s.risk == 1.0
    assert s.update(entry) is None
    s.update(bar(1, 100.0, 100.1, 97.7, 98.0))  # ask low 97.9 <= 98: rungs 1R and 2R
    assert s.position_closed
    trade = s.update(bar(2, 98.0, 98.1, 96.5, 96.8))  # ask low 96.7 <= 97: rung 3
    assert trade is not None and trade.exit_reason is ExitReason.TARGET
    assert trade.r_net == pytest.approx(2.0)
    stopped = sim(Side.SHORT, stop=101.0, entry=entry)
    stopped.update(entry)
    out = stopped.update(bar(1, 100.5, 101.0, 100.4, 100.9))
    assert out is not None and out.exit_fill == pytest.approx(101.1)
    assert out.r_net == pytest.approx(-1.1)


def test_commission_is_subtracted_in_r() -> None:
    costs = CostModel(0.2, 0.1, 10)
    s = sim(costs=costs)
    s.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    s.update(bar(1, 100.3, 102.5, 100.0, 102.0))
    trade = s.update(bar(2, 102.0, 103.5, 101.8, 103.0))
    assert trade is not None and trade.r_net == pytest.approx(2.0 - 0.2004)


def test_entry_beyond_the_stop_is_rejected_and_rung_keys_are_compact() -> None:
    with pytest.raises(ValueError, match="stop"):
        sim(stop=100.5)
    assert [rung_key(r) for r in (1, 2.5, 10)] == ["1", "2.5", "10"]


def test_stop_and_timeout_returns_are_stored_for_other_exit_policies() -> None:
    stopped = sim()
    stopped.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    trade = stopped.update(bar(1, 100.0, 100.2, 99.0, 99.4))
    assert trade is not None and trade.stop_r == pytest.approx(-1.1) and trade.timeout_r is None

    timed = sim(max_hold=3)
    for i in range(3):
        timed.update(bar(i, 100.2, 100.6, 99.8, 100.4))
    trade = timed.update(bar(3, 100.4, 100.5, 100.3, 100.4))
    assert trade is not None and trade.timeout_r == pytest.approx(0.2) and trade.stop_r is None

    both = sim()
    both.update(bar(0, 100.0, 100.5, 99.5, 100.3))
    both.update(bar(1, 100.3, 102.5, 100.0, 102.0))  # rung 1 and 2: the reference target
    trade = both.update(bar(2, 102.0, 102.1, 99.0, 99.5))  # then the stop, after the target
    assert trade is not None and trade.exit_reason is ExitReason.TARGET
    assert trade.r_net == pytest.approx(2.0) and trade.stop_r == pytest.approx(-1.1)


def test_target_first_ambiguity_credits_the_rungs_of_the_stop_bar() -> None:
    s = TradeSim(
        "t", Side.LONG, 99.2, bar(0, 100.0, 100.5, 99.5, 100.3), COSTS, [1, 2, 3], 1, 60,
        target_first=True,
    )  # fmt: skip
    trade = s.update(bar(1, 100.0, 101.5, 99.0, 100.0))  # rung 1 and the stop in one bar
    assert trade is not None and trade.ambiguous_bars == 1
    assert trade.ladder["1"] is not None and trade.ladder["2"] is None
    assert trade.exit_reason is ExitReason.TARGET and trade.stop_r is not None


def _be_trade(bars: list[Bar], target_first: bool = False) -> Trade:
    s = TradeSim(
        "t", Side.LONG, 99.2, bar(0, 100.0, 100.5, 99.5, 100.3), COSTS, [1, 2, 3], 2, 60,
        target_first=target_first, be_triggers_r=(1.0,),
    )  # fmt: skip
    for b in bars:  # entry fill 100.2, risk 1.0, rung 1 at 101.2, rung 2 at 102.2, stop 99.2
        s.update(b)
    trade = s.flush()
    assert trade is not None
    return trade


def test_break_even_exit_is_classified_by_what_the_original_path_did_next() -> None:
    from edgebench.results import be_outcome

    arm = bar(1, 100.6, 101.3, 100.5, 101.0)  # reaches +1R
    back = bar(2, 100.6, 100.8, 100.1, 100.5)  # trades back to the entry fill 100.2
    winner = _be_trade([arm, back, bar(3, 100.5, 102.4, 100.4, 102.0)])
    r, cls = be_outcome(winner, 1.0, 2.0)
    assert cls == "be_winner" and abs(r - (-0.1)) < 1e-9  # BE fill 100.1: slippage only
    loser = _be_trade([arm, back, bar(3, 100.5, 100.6, 99.0, 99.1)])
    assert be_outcome(loser, 1.0, 2.0)[1] == "be_loser"
    assert be_outcome(loser, 1.0, 2.0)[0] == be_outcome(winner, 1.0, 2.0)[0]
    clean = _be_trade([arm, bar(2, 101.0, 102.4, 100.9, 102.0)])
    assert be_outcome(clean, 1.0, 2.0) == (2.0, "target")
    unarmed = _be_trade([bar(1, 100.2, 100.9, 99.0, 99.1)])
    assert be_outcome(unarmed, 1.0, 2.0)[1] == "none"
    assert be_outcome(unarmed, 1.0, 2.0)[0] == unarmed.stop_r


def test_break_even_and_target_in_one_bar_follow_the_ambiguity_rule() -> None:
    from edgebench.results import be_outcome

    arm = bar(1, 100.6, 101.3, 100.5, 101.0)
    both = bar(2, 100.6, 102.4, 100.1, 102.0)  # returns to the entry and reaches +2R
    assert be_outcome(_be_trade([arm, both]), 1.0, 2.0)[1] == "be_winner"
    assert be_outcome(_be_trade([arm, both], target_first=True), 1.0, 2.0, True)[1] == "target"
