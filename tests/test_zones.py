from datetime import UTC, datetime, timedelta

import pytest

from edgebench.config.schema import FractalConfig, FvgConfig
from edgebench.contracts import Bar, Direction, Zone, ZoneKind
from edgebench.zones import BarWindow, FractalDetector, FvgDetector, WilderATR

T0 = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)


def bar(hour: int, high: float, low: float, complete: bool = True) -> Bar:
    mid = (high + low) / 2
    return Bar(T0 + hour * HOUR, mid, high, low, mid, 1.0, "H1", complete)


def run(detector: FvgDetector | FractalDetector, bars: list[Bar]) -> list[list[Zone]]:
    return [detector.on_bar(b) for b in bars]


# ---- ATR ---------------------------------------------------------------------------------


def test_atr_known_answer_with_wilder_smoothing_and_gap_true_range() -> None:
    atr = WilderATR(3)
    assert atr.update(bar(0, 11, 9)) is None  # TR 2 (no previous close)
    assert atr.update(bar(1, 11, 9)) is None
    assert atr.update(bar(2, 11, 9)) == pytest.approx(2.0)  # mean of 2, 2, 2
    # previous close 10; high 15 low 14 gives TR = max(1, 5, 4) = 5
    assert atr.update(bar(3, 15, 14)) == pytest.approx((2.0 * 2 + 5) / 3)
    assert atr.value == pytest.approx(3.0)


def test_atr_rejects_a_bad_period() -> None:
    with pytest.raises(ValueError):
        WilderATR(0)


# ---- window ------------------------------------------------------------------------------


def test_window_resets_on_gaps_and_incomplete_bars() -> None:
    window = BarWindow(3)
    assert [window.push(bar(h, 2, 1)) for h in (0, 1, 2)] == [False, False, True]
    assert window.push(bar(4, 2, 1)) is False  # hour 3 is missing
    assert len(window.bars) == 1
    window.push(bar(5, 2, 1))
    assert window.push(bar(6, 2, 1, complete=False)) is False
    assert window.bars == ()
    with pytest.raises(ValueError, match="H1"):
        window.push(Bar(T0, 1, 1, 1, 1, 0, "M1"))


# ---- FVG ---------------------------------------------------------------------------------

# Two warm-up bars with range 2, then c1, c2, c3. ATR period 2 keeps the arithmetic small.
WARMUP = [bar(0, 11, 9), bar(1, 11, 9)]


def fvg(**overrides: object) -> FvgDetector:
    cfg = FvgConfig.model_validate({"min_size_atr_h1": 0.0, **overrides})
    return FvgDetector(cfg, "EURUSD", atr_period=2)


def test_bull_fvg_known_answer() -> None:
    bars = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(4, 14, 12)]
    out = run(fvg(), bars)
    assert [len(z) for z in out] == [0, 0, 0, 0, 1]  # appears exactly when c3 closes
    (zone,) = out[4]
    assert (zone.kind, zone.direction) == (ZoneKind.FVG, Direction.BULL)
    assert (zone.low, zone.high) == (10, 12)  # [high(c1), low(c3)]
    assert zone.formed_at == zone.known_at == bars[4].ts_close
    assert zone.zone_id == "EURUSD:FVG:BULL:20240101T050000Z"


def test_bear_fvg_known_answer() -> None:
    bars = WARMUP + [bar(2, 14, 12), bar(3, 12.5, 8), bar(4, 10, 6)]
    (zone,) = run(fvg(), bars)[4]
    assert zone.direction is Direction.BEAR
    assert (zone.low, zone.high) == (10, 12)  # [high(c3), low(c1)]


def test_touching_or_overlapping_bars_make_no_gap() -> None:
    bars = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(4, 14, 10)]  # low(c3) == high(c1)
    assert run(fvg(), bars)[4] == []


def test_size_and_displacement_filters_use_the_atr_known_at_c3() -> None:
    bars = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(4, 14, 12)]
    atr = WilderATR(2)
    values = [atr.update(b) for b in bars]
    size = 12 - 10
    assert run(fvg(min_size_atr_h1=size / values[4] * 0.99), bars)[4] != []
    assert run(fvg(min_size_atr_h1=size / values[4] * 1.01), bars)[4] == []
    body = abs(bars[3].close - bars[3].open)  # zero here: a doji-like middle bar
    assert run(fvg(min_displacement_body_atr_h1=0.5), bars)[4] == []
    assert body == 0.0


def test_no_zone_during_atr_warm_up_or_when_disabled() -> None:
    early = [bar(0, 10, 9), bar(1, 13, 9.5), bar(2, 14, 12)]  # gap exists but ATR(2) is ready
    assert run(fvg(), early)[2] != []
    detector = FvgDetector(FvgConfig(min_size_atr_h1=0.0), "EURUSD", atr_period=5)
    assert run(detector, early)[2] == []  # ATR(5) needs 5 bars
    assert (
        run(fvg(enabled=False), WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(4, 14, 12)])[4] == []
    )


def test_no_pattern_across_a_time_gap_or_an_incomplete_bar() -> None:
    gap = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(5, 14, 12)]  # hour 4 missing
    assert all(z == [] for z in run(fvg(), gap))
    partial = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5, complete=False), bar(4, 14, 12)]
    assert all(z == [] for z in run(fvg(), partial))


def test_params_hash_changes_with_the_config() -> None:
    bars = WARMUP + [bar(2, 10, 9), bar(3, 13, 9.5), bar(4, 14, 12)]
    a = run(fvg(), bars)[4][0].params_hash
    b = run(fvg(max_age_h1_bars=50), bars)[4][0].params_hash
    assert a and b and a != b


# ---- fractals ----------------------------------------------------------------------------


def fractal(left: int = 2, right: int = 2) -> FractalDetector:
    return FractalDetector(FractalConfig(left=left, right=right), "EURUSD")


def test_pivot_high_is_known_only_after_the_right_bars_close() -> None:
    bars = [bar(i, h, h - 1) for i, h in enumerate([2, 3, 6, 3, 2])]
    out = run(fractal(), bars)
    assert [len(z) for z in out] == [0, 0, 0, 0, 1]  # nothing at the pivot bar itself
    (zone,) = out[4]
    assert (zone.kind, zone.direction) == (ZoneKind.FRACTAL, Direction.BEAR)
    assert zone.low == zone.high == 6
    assert zone.extreme_ts == bars[2].ts_open
    assert zone.formed_at == bars[2].ts_close
    assert zone.known_at == bars[4].ts_close
    assert zone.known_at - zone.formed_at == 2 * HOUR  # `right` bars later


def test_pivot_low_known_answer() -> None:
    bars = [bar(i, low + 1, low) for i, low in enumerate([5, 4, 1, 4, 5])]
    (zone,) = run(fractal(), bars)[4]
    assert (zone.direction, zone.low, zone.high) == (Direction.BULL, 1, 1)


def test_equal_extremes_are_not_fractals() -> None:
    bars = [bar(i, h, h - 1) for i, h in enumerate([2, 3, 6, 6, 2])]
    assert all(z == [] for z in run(fractal(), bars))


def test_one_one_fractal_and_asymmetric_windows() -> None:
    bars = [bar(i, h, h - 1) for i, h in enumerate([2, 6, 3])]
    assert len(run(fractal(1, 1), bars)[2]) == 1
    wide = [bar(i, h, h - 1) for i, h in enumerate([2, 3, 6, 3])]
    (zone,) = run(fractal(2, 1), wide)[3]
    assert zone.known_at == wide[3].ts_close


def test_outside_bar_gives_both_a_high_and_a_low_level() -> None:
    bars = [bar(0, 5, 4), bar(1, 5.5, 4.5), bar(2, 9, 1), bar(3, 5.5, 4.5), bar(4, 5, 4)]
    zones = run(fractal(), bars)[4]
    assert {z.direction for z in zones} == {Direction.BEAR, Direction.BULL}


def test_fractal_window_is_reset_by_gaps() -> None:
    hours = [0, 1, 2, 3, 5, 6, 7, 8, 9]  # hour 4 missing
    highs = [2, 3, 6, 3, 2, 3, 6, 3, 2]
    bars = [bar(h, v, v - 1) for h, v in zip(hours, highs, strict=True)]
    out = run(fractal(), bars)
    assert out[4] == []  # the first candidate pivot spans the gap and is dropped
    assert len(out[8]) == 1  # the second one is made of five adjacent bars
