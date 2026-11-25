"""Pattern detectors on hand-built M1 bars. Zone BULL [100, 102] unless stated, ATR(M1) = 1."""

from datetime import UTC, datetime, timedelta

import pytest

from edgebench.config.schema import (
    InsideConfig,
    PatternsConfig,
    RejectionConfig,
    StallConfig,
    SweepConfig,
)
from edgebench.contracts import Bar, Direction, Observation, Zone, ZoneKind
from edgebench.patterns import (
    InsideDetector,
    PatternContext,
    PatternDetector,
    PatternSet,
    RejectionDetector,
    StallDetector,
    SweepDetector,
    pivot_levels,
)

T0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
Row = tuple[float, float, float, float]  # open, high, low, close


def bars(rows: list[Row], tf: str = "M1", start: datetime = T0) -> list[Bar]:
    step = {"M1": MIN, "M3": 3 * MIN}[tf]
    return [Bar(start + i * step, o, h, lo, c, 1.0, tf) for i, (o, h, lo, c) in enumerate(rows)]


def zone(direction: Direction = Direction.BULL) -> Zone:
    return Zone("z", "EURUSD", ZoneKind.FVG, direction, 100.0, 102.0, T0, T0)


def run(
    detector: PatternDetector,
    rows: list[Row],
    direction: Direction = Direction.BULL,
    h1_levels: tuple[float, ...] = (),
    m3_history: tuple[Bar, ...] = (),
) -> list[tuple[int, Observation]]:
    """Feed bars one by one; returns (bar index, observation)."""
    seq = bars(rows)
    out: list[tuple[int, Observation]] = []
    for i, bar in enumerate(seq):
        ctx = PatternContext(
            zone=zone(direction),
            episode_index=0,
            touch_start=T0,
            atr_m1=1.0,
            history=tuple(seq[: i + 1]),
            m3_history=m3_history,
            h1_levels=h1_levels,
            bars_since_touch=i,
        )
        out.extend((i, o) for o in detector.on_bar(bar, ctx))
    return out


def mirror(rows: list[Row], axis: float = 200.0) -> list[Row]:
    """Reflect prices around ``axis`` so a BULL fixture becomes its BEAR twin."""
    return [(axis - o, axis - lo, axis - h, axis - c) for o, h, lo, c in rows]


# -- rejection ---------------------------------------------------------------------------------


def test_rejection_long_lower_wick_closing_high() -> None:
    det = RejectionDetector(RejectionConfig())
    hits = run(det, [(101.0, 101.2, 100.0, 101.1)])  # wick 0.83 of range, close at 92%
    assert [i for i, _ in hits] == [0]
    obs = hits[0][1]
    assert obs.detector == "rejection" and obs.direction is Direction.BULL
    assert obs.ts_decision == T0 + MIN
    assert obs.refs["extreme"] == 100.0
    assert obs.metrics["wick_ratio"] == pytest.approx(1.0 / 1.2)


@pytest.mark.parametrize(
    "row",
    [
        (101.0, 102.0, 100.5, 100.8),  # short wick
        (100.8, 101.2, 100.0, 100.75),  # wick 0.625 but the close is only 62% up
        (105.0, 106.0, 104.0, 105.9),  # does not reach the zone
        (101.0, 101.0, 101.0, 101.0),  # zero range
    ],
)
def test_rejection_negative_cases(row: Row) -> None:
    assert run(RejectionDetector(RejectionConfig()), [row]) == []


def test_rejection_bear_mirror() -> None:
    row = mirror([(101.0, 101.2, 100.0, 101.1)])
    z_bear = Zone("z", "EURUSD", ZoneKind.FVG, Direction.BEAR, 98.0, 100.0, T0, T0)
    seq = bars(row)
    ctx = PatternContext(z_bear, 0, T0, 1.0, tuple(seq))
    obs = RejectionDetector(RejectionConfig()).on_bar(seq[0], ctx)
    assert len(obs) == 1 and obs[0].direction is Direction.BEAR and obs[0].refs["extreme"] == 100.0


# -- stall -------------------------------------------------------------------------------------

DROP: Row = (102.5, 102.6, 101.0, 101.2)  # the move into the zone
QUIET: list[Row] = [
    (101.2, 101.4, 101.0, 101.1),  # range 0.4
    (101.1, 101.25, 100.95, 101.05),  # 0.3, low 0.05 under the prior low
    (101.05, 101.35, 100.95, 101.2),  # 0.4
]


def test_stall_fires_once_when_the_third_quiet_bar_closes() -> None:
    quiet_more: Row = (101.2, 101.4, 101.0, 101.1)
    hits = run(StallDetector(StallConfig()), [DROP, *QUIET, quiet_more])
    assert [i for i, _ in hits] == [3]  # edge-triggered: not again on bar 4
    assert hits[0][1].refs["extreme"] == 100.95


def test_stall_needs_small_ranges_and_no_new_extreme() -> None:
    det = StallConfig()
    wide = [DROP, QUIET[0], (101.1, 101.8, 101.0, 101.5), QUIET[2]]  # range 0.8 > 0.5
    assert run(StallDetector(det), wide) == []
    extends = [DROP, QUIET[0], (101.1, 101.15, 100.7, 100.8), (100.8, 101.0, 100.6, 100.9)]
    assert run(StallDetector(det), extends) == []  # lows 0.3-0.4 beyond the prior low


def test_stall_bear_mirror_and_n_bars() -> None:
    rows = mirror([DROP, *QUIET])
    assert [i for i, _ in run(StallDetector(StallConfig()), rows, Direction.BEAR)] == [3]
    assert run(StallDetector(StallConfig(n_bars=4)), [DROP, *QUIET]) == []


# -- inside ------------------------------------------------------------------------------------

MOTHER: Row = (101.0, 103.0, 100.0, 100.5)
INNER: Row = (100.8, 102.0, 100.4, 101.0)


def test_inside_bar_range_mode() -> None:
    hits = run(InsideDetector(InsideConfig()), [MOTHER, INNER])
    assert [i for i, _ in hits] == [1]
    assert hits[0][1].refs == {"mother_high": 103.0, "mother_low": 100.0}
    assert hits[0][1].metrics["size_ratio"] == pytest.approx(1.6 / 3.0)


def test_inside_requires_containment_and_counts_a_chain() -> None:
    poke: Row = (100.8, 103.1, 100.4, 101.0)  # high above the mother
    assert run(InsideDetector(InsideConfig()), [MOTHER, poke]) == []
    chain = [MOTHER, INNER, (100.9, 101.5, 100.6, 101.1)]
    assert [i for i, _ in run(InsideDetector(InsideConfig(min_count=2)), chain)] == [2]
    assert [i for i, _ in run(InsideDetector(InsideConfig(min_count=1)), chain)] == [1]


def test_inside_body_mode_ignores_wicks() -> None:
    wicky: Row = (100.8, 104.0, 99.0, 101.0)  # body 100.8..101.0 inside the mother body
    mother: Row = (101.0, 103.0, 100.0, 102.0)  # body 101.0..102.0 -> the wicky body pokes below
    assert run(InsideDetector(InsideConfig(mode="body")), [mother, wicky]) == []
    ok: Row = (101.2, 104.0, 99.0, 101.8)
    assert [i for i, _ in run(InsideDetector(InsideConfig(mode="body")), [mother, ok])] == [1]
    assert run(InsideDetector(InsideConfig(mode="range")), [mother, ok]) == []


# -- sweep -------------------------------------------------------------------------------------


def test_sweep_of_the_zone_edge_wick_closes_back_inside() -> None:
    cfg = SweepConfig(references=["zone_edge"])
    hits = run(SweepDetector(cfg), [(101.0, 101.5, 100.5, 100.8), (100.9, 101.0, 99.5, 100.4)])
    assert [i for i, _ in hits] == [1]
    obs = hits[0][1]
    assert obs.refs == {"level": 100.0, "extreme": 99.5}
    assert obs.metrics["depth_atr"] == pytest.approx(0.5)
    assert obs.metrics["return_bars"] == 1.0


def test_sweep_returns_within_max_return_bars_only() -> None:
    cfg = SweepConfig(references=["zone_edge"], max_return_bars=3)
    pierce: Row = (100.5, 100.6, 99.5, 99.7)  # closes beyond: no return yet
    ok = run(SweepDetector(cfg), [pierce, (99.7, 99.9, 99.4, 99.8), (99.8, 100.6, 99.7, 100.3)])
    assert [(i, o.metrics["return_bars"]) for i, o in ok] == [(2, 3.0)]
    late = run(
        SweepDetector(cfg),
        [pierce, (99.7, 99.9, 99.4, 99.8), (99.8, 99.9, 99.5, 99.6), (99.6, 100.6, 99.6, 100.3)],
    )
    assert late == []  # the return came on the 4th bar


def test_sweep_needs_min_depth_and_is_consumed_once() -> None:
    cfg = SweepConfig(references=["zone_edge"], min_depth_atr_m1=0.3)
    shallow: Row = (100.5, 100.6, 99.8, 100.4)  # depth 0.2 < 0.3
    deep: Row = (100.5, 100.6, 99.6, 100.4)  # depth 0.4
    assert run(SweepDetector(cfg), [shallow]) == []
    again = run(SweepDetector(cfg), [deep, deep])
    assert [i for i, _ in again] == [0]  # the level is consumed by the first pierce


def test_a_bar_opening_beyond_the_level_does_not_sweep_it() -> None:
    cfg = SweepConfig(references=["zone_edge"])
    gap: Row = (99.5, 100.6, 99.3, 100.4)
    assert run(SweepDetector(cfg), [gap]) == []


def test_sweep_of_h1_level_from_context_and_bear_mirror() -> None:
    cfg = SweepConfig(references=["h1_fractal"])
    back: Row = (101.0, 101.2, 98.5, 99.1)  # pierces 99.0 by 0.5 and closes back above it
    hits = run(SweepDetector(cfg), [back], h1_levels=(99.0,))
    assert [(i, o.refs["level"]) for i, o in hits] == [(0, 99.0)]
    assert run(SweepDetector(cfg), [(101.0, 101.2, 98.5, 98.8)], h1_levels=(99.0,)) == []
    assert run(SweepDetector(cfg), [back]) == []  # no known level, nothing to sweep
    bear = run(SweepDetector(cfg), mirror([back]), Direction.BEAR, h1_levels=(101.0,))
    assert [i for i, _ in bear] == [0] and bear[0][1].direction is Direction.BEAR


def test_sweep_of_an_m1_fractal_only_after_it_is_confirmed() -> None:
    # bar2 is a pivot low (99.0); it is confirmed only after bars 3 and 4 have closed
    rows: list[Row] = [
        (101.0, 101.5, 100.0, 100.5),
        (100.5, 100.8, 99.6, 99.8),
        (99.8, 100.0, 99.0, 99.5),
        (99.5, 100.2, 99.4, 100.0),
        (100.0, 100.6, 99.5, 100.4),
        (100.4, 100.5, 98.6, 99.4),  # pierces 99.0, closes above it -> sweep
    ]
    cfg = SweepConfig(references=["ltf_fractal_m1"])
    hits = run(SweepDetector(cfg), rows)
    assert [i for i, _ in hits] == [5]
    assert hits[0][1].refs["level"] == 99.0
    early = rows[:3] + [(99.5, 100.2, 98.5, 99.4)]  # pierces before confirmation
    assert run(SweepDetector(cfg), early) == []


def test_sweep_of_an_m3_fractal_uses_complete_m3_bars() -> None:
    m3 = bars(
        [
            (101.0, 101.5, 100.0, 100.5),
            (100.5, 100.8, 99.6, 99.8),
            (99.8, 100.0, 99.0, 99.5),
            (99.5, 100.2, 99.4, 100.0),
            (100.0, 100.6, 99.5, 100.4),
        ],
        tf="M3",
        start=T0 - 30 * MIN,
    )
    cfg = SweepConfig(references=["ltf_fractal_m3"])
    hits = run(SweepDetector(cfg), [(100.4, 100.5, 98.6, 99.4)], m3_history=tuple(m3))
    assert [o.refs["level"] for _, o in hits] == [99.0]


def test_pivot_levels_helper() -> None:
    seq = bars([(1, 2, 0.5, 1), (1, 2, 0.4, 1), (1, 2, 0.1, 1), (1, 2, 0.4, 1), (1, 2, 0.5, 1)])
    assert pivot_levels(seq, Direction.BULL, 2, 2) == [0.1]
    assert pivot_levels(seq[:4], Direction.BULL, 2, 2) == []  # right side not closed yet
    pierced = [*seq, *bars([(1, 2, 0.05, 1)], start=T0 + 5 * MIN)]
    assert pivot_levels(pierced, Direction.BULL, 2, 2) == []


# -- pattern set -------------------------------------------------------------------------------


def test_pattern_set_runs_enabled_detectors_and_respects_the_window() -> None:
    cfg = PatternsConfig.model_validate({"stall": {"enabled": False}})
    ps = PatternSet(cfg, window_bars=10)
    assert ps.names == ["sweep", "rejection", "inside"]
    seq = bars([(101.0, 101.2, 100.0, 101.1)])
    ctx = PatternContext(zone(), 0, T0, 1.0, tuple(seq), bars_since_touch=2)
    assert [o.detector for o in ps.on_bar(seq[0], ctx)] == ["rejection"]
    late = PatternContext(zone(), 0, T0, 1.0, tuple(seq), bars_since_touch=11)
    assert ps.on_bar(seq[0], late) == []


def test_context_validation() -> None:
    seq = bars([(101.0, 101.2, 100.0, 101.1)])
    with pytest.raises(ValueError, match="history"):
        PatternContext(zone(), 0, T0, 1.0, ())
    with pytest.raises(ValueError, match="atr"):
        PatternContext(zone(), 0, T0, 0.0, tuple(seq))


# -- baseline ----------------------------------------------------------------------------------


def test_baseline_is_deterministic_and_close_to_its_probability() -> None:
    from edgebench.config.schema import BaselineConfig
    from edgebench.patterns import BaselineDetector

    rows: list[Row] = [(101.0, 101.5, 100.5, 101.2)] * 2000
    always = run(BaselineDetector(BaselineConfig(enabled=True, probability=1.0)), rows[:5])
    assert len(always) == 5 and always[0][1].refs["extreme"] == 100.5
    a = run(BaselineDetector(BaselineConfig(enabled=True, probability=0.1)), rows)
    b = run(BaselineDetector(BaselineConfig(enabled=True, probability=0.1)), rows)
    assert [i for i, _ in a] == [i for i, _ in b]
    assert 0.07 < len(a) / 2000 < 0.13
    other = run(BaselineDetector(BaselineConfig(enabled=True, probability=0.1, seed=1)), rows)
    assert [i for i, _ in other] != [i for i, _ in a]
    bear = run(
        BaselineDetector(BaselineConfig(enabled=True, probability=1.0)), rows[:1], Direction.BEAR
    )
    assert bear[0][1].refs["extreme"] == 101.5
