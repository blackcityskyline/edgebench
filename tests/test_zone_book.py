from datetime import UTC, datetime, timedelta

import pytest

from edgebench.config.schema import FractalConfig, FvgConfig
from edgebench.contracts import (
    Bar,
    Direction,
    Zone,
    ZoneEvent,
    ZoneEventType,
    ZoneKind,
)
from edgebench.zones import ZoneBook

T0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)
E = ZoneEventType

ABOVE = (14.0, 13.0, 13.5)  # (high, low, close): clear of a zone at 10..12
INSIDE = (11.5, 10.5, 11.0)
BELOW = (9.0, 8.0, 8.5)


def m1(minute: int, high: float, low: float, close: float) -> Bar:
    return Bar(T0 + minute * MIN, close, high, low, close, 1.0, "M1")


def zone(
    direction: Direction = Direction.BULL,
    low: float = 10.0,
    high: float = 12.0,
    kind: ZoneKind = ZoneKind.FVG,
    known_at: datetime = T0,
) -> Zone:
    if kind is ZoneKind.FRACTAL:
        return Zone(
            "z1", "EURUSD", kind, direction, low, low, known_at - 2 * MIN, known_at,
            extreme_ts=known_at - 3 * MIN,
        )  # fmt: skip
    return Zone("z1", "EURUSD", kind, direction, low, high, known_at, known_at)


def book(episode_gap: int = 3, **fvg: object) -> ZoneBook:
    return ZoneBook(FvgConfig.model_validate(fvg), FractalConfig(), episode_gap)


def feed(b: ZoneBook, bars: list[tuple[float, float, float]]) -> list[list[ZoneEvent]]:
    return [b.on_m1(m1(i, *bar)) for i, bar in enumerate(bars)]


def types(events: list[list[ZoneEvent]]) -> list[list[ZoneEventType]]:
    return [[e.type for e in step] for step in events]


def test_episode_starts_on_touch_and_ends_after_the_gap_then_zone_is_mitigated() -> None:
    b = book(episode_gap=3)
    b.add(zone())
    out = feed(b, [ABOVE, INSIDE, INSIDE, ABOVE, ABOVE, ABOVE])
    assert types(out) == [[], [E.TOUCH_START], [], [], [], [E.TOUCH_END, E.MITIGATED]]
    start, end = out[1][0], out[5][0]
    assert start.ts == T0 + 2 * MIN  # stamped with the close of the touching bar
    assert (start.episode_index, end.episode_index) == (0, 0)
    assert b.live_zones() == []


def test_a_touch_during_the_gap_keeps_the_same_episode_alive() -> None:
    b = book(episode_gap=3)
    b.add(zone())
    out = feed(b, [INSIDE, ABOVE, ABOVE, INSIDE, ABOVE, ABOVE])
    assert types(out) == [[E.TOUCH_START], [], [], [], [], []]
    assert b.active_episode("z1") == 0


def test_max_episodes_allows_a_second_touch_with_the_next_index() -> None:
    b = book(episode_gap=2, max_episodes=2)
    b.add(zone())
    out = feed(b, [INSIDE, ABOVE, ABOVE, INSIDE, ABOVE, ABOVE])
    assert types(out) == [
        [E.TOUCH_START],
        [],
        [E.TOUCH_END],
        [E.TOUCH_START],
        [],
        [E.TOUCH_END, E.MITIGATED],
    ]
    assert [e.episode_index for step in out for e in step if e.type is E.TOUCH_START] == [0, 1]


def test_a_zone_cannot_be_touched_before_it_is_known() -> None:
    b = book()
    b.add(zone(known_at=T0 + 5 * MIN))
    out = feed(b, [INSIDE] * 5 + [INSIDE])  # minutes 0..4 are before known_at
    assert types(out)[:5] == [[]] * 5
    assert types(out)[5] == [E.TOUCH_START]


def test_close_through_invalidates_but_a_wick_sweep_does_not() -> None:
    sweep = (11.0, 9.5, 10.5)  # wicks below 10 and closes back inside
    b = book(episode_gap=5)
    b.add(zone())
    assert types(feed(b, [INSIDE, sweep])) == [[E.TOUCH_START], []]
    out = feed(b, [(11.0, 9.0, 9.5)])  # closes below the zone low
    assert [e.type for e in out[0]] == [E.TOUCH_END, E.INVALIDATED]
    assert b.live_zones() == []


def test_bear_zone_is_the_mirror_image() -> None:
    b = book()
    b.add(zone(Direction.BEAR))
    out = feed(b, [INSIDE, (13.0, 11.0, 12.5)])  # closes above the zone high
    assert types(out) == [[E.TOUCH_START], [E.TOUCH_END, E.INVALIDATED]]


def test_a_bar_entirely_beyond_the_zone_invalidates_without_a_touch() -> None:
    b = book()
    b.add(zone())
    assert types(feed(b, [BELOW])) == [[E.INVALIDATED]]


def test_full_fill_needs_the_low_to_reach_the_far_edge() -> None:
    b = book(invalid_on="full_fill", episode_gap=5)
    b.add(zone())
    assert types(feed(b, [(11.0, 10.2, 10.5)])) == [[E.TOUCH_START]]
    assert types(feed(b, [(11.0, 9.9, 10.5)])) == [[E.TOUCH_END, E.INVALIDATED]]


def test_never_mode_ignores_closes_through_the_zone() -> None:
    b = book(invalid_on="never", episode_gap=5)
    b.add(zone())
    assert types(feed(b, [INSIDE, BELOW])) == [[E.TOUCH_START], []]
    assert len(b.live_zones()) == 1


def test_first_touch_mode_retires_the_zone_when_the_first_episode_ends() -> None:
    b = book(invalid_on="first_touch", episode_gap=2, max_episodes=3)
    b.add(zone())
    out = feed(b, [INSIDE, ABOVE, ABOVE])
    assert types(out) == [[E.TOUCH_START], [], [E.TOUCH_END, E.INVALIDATED]]


def test_zones_expire_by_age_and_end_a_running_episode() -> None:
    b = book(episode_gap=5, max_age_h1_bars=1)
    b.add(zone())
    out = [b.on_m1(m1(0, *INSIDE)), b.on_m1(m1(59, *INSIDE))]
    assert types(out) == [[E.TOUCH_START], [E.TOUCH_END, E.EXPIRED]]
    assert out[1][0].ts == T0 + 60 * MIN  # age is measured to the bar close


def test_fractal_level_is_touched_only_when_the_range_reaches_it() -> None:
    b = ZoneBook(FvgConfig(), FractalConfig(), 3)
    b.add(zone(kind=ZoneKind.FRACTAL, low=11.0))
    assert types(feed(b, [(12.0, 11.2, 11.5)])) == [[]]  # stays above the level
    assert types([b.on_m1(m1(1, 11.5, 10.8, 11.2))]) == [[E.TOUCH_START]]


def test_fractal_uses_its_own_config() -> None:
    b = ZoneBook(FvgConfig(), FractalConfig(max_episodes=2, invalid_on="never"), 1)
    b.add(zone(kind=ZoneKind.FRACTAL, low=11.0))
    out = feed(b, [(11.5, 10.5, 11.0), ABOVE, (11.5, 10.5, 11.0), ABOVE])
    assert types(out) == [
        [E.TOUCH_START],
        [E.TOUCH_END],
        [E.TOUCH_START],
        [E.TOUCH_END, E.MITIGATED],
    ]


def test_independent_zones_and_input_validation() -> None:
    b = book(episode_gap=5)
    b.add(zone())
    second = Zone("z2", "EURUSD", ZoneKind.FVG, Direction.BEAR, 20.0, 22.0, T0, T0)
    b.add(second)
    out = b.on_m1(m1(0, *INSIDE))
    assert [(e.zone_id, e.type) for e in out] == [("z1", E.TOUCH_START)]
    with pytest.raises(ValueError, match="already tracked"):
        b.add(second)
    with pytest.raises(ValueError, match="M1"):
        b.on_m1(Bar(T0, 1, 1, 1, 1, 0, "H1"))
    with pytest.raises(ValueError):
        ZoneBook(FvgConfig(), FractalConfig(), 0)
