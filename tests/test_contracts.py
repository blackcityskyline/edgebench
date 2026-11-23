from datetime import UTC, datetime, timedelta, timezone

import pytest

from edgebench.contracts import (
    Bar,
    Direction,
    ExitReason,
    OrderIntent,
    Side,
    Trade,
    Zone,
    ZoneKind,
    candidate_id,
    event_id,
    make_run_id,
    zone_id,
)

T0 = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)


def bar(**overrides: object) -> Bar:
    fields: dict[str, object] = {
        "ts_open": T0,
        "open": 1.0,
        "high": 1.2,
        "low": 0.9,
        "close": 1.1,
        "volume": 10.0,
        "tf": "M1",
    }
    fields.update(overrides)
    return Bar(**fields)  # type: ignore[arg-type]


def test_bar_ts_close_depends_on_timeframe() -> None:
    assert bar().ts_close == T0 + timedelta(minutes=1)
    assert bar(tf="H1").ts_close == T0 + timedelta(hours=1)


def test_bar_rejects_naive_and_non_utc_timestamps() -> None:
    with pytest.raises(ValueError, match="UTC"):
        bar(ts_open=datetime(2026, 1, 5, 9, 0))
    with pytest.raises(ValueError, match="UTC"):
        bar(ts_open=datetime(2026, 1, 5, 9, 0, tzinfo=timezone(timedelta(hours=3))))


def test_bar_rejects_inconsistent_ohlc() -> None:
    with pytest.raises(ValueError):
        bar(high=1.05)  # close 1.1 above high
    with pytest.raises(ValueError):
        bar(low=1.05)  # open 1.0 below low
    with pytest.raises(ValueError):
        bar(tf="M5")


def test_fvg_is_known_when_formed() -> None:
    formed = T0 + timedelta(hours=3)
    zone = Zone("z", "EURUSD", ZoneKind.FVG, Direction.BULL, 1.0, 1.1, formed, formed)
    assert zone.known_at == zone.formed_at
    with pytest.raises(ValueError, match="known at the moment"):
        Zone(
            "z",
            "EURUSD",
            ZoneKind.FVG,
            Direction.BULL,
            1.0,
            1.1,
            formed,
            formed + timedelta(hours=1),
        )


def test_fractal_level_is_known_only_after_confirmation() -> None:
    pivot_open = T0
    formed = T0 + timedelta(hours=1)  # close of the pivot bar
    known = T0 + timedelta(hours=3)  # two more bars close
    zone = Zone(
        "z",
        "EURUSD",
        ZoneKind.FRACTAL,
        Direction.BEAR,
        1.2,
        1.2,
        formed,
        known,
        extreme_ts=pivot_open,
    )
    assert zone.known_at > zone.formed_at
    with pytest.raises(ValueError, match="single level"):
        Zone(
            "z",
            "EURUSD",
            ZoneKind.FRACTAL,
            Direction.BEAR,
            1.1,
            1.2,
            formed,
            known,
            extreme_ts=pivot_open,
        )
    with pytest.raises(ValueError, match="extreme_ts"):
        Zone("z", "EURUSD", ZoneKind.FRACTAL, Direction.BEAR, 1.2, 1.2, formed, known)
    with pytest.raises(ValueError, match="precede"):
        Zone(
            "z",
            "EURUSD",
            ZoneKind.FRACTAL,
            Direction.BEAR,
            1.2,
            1.2,
            formed,
            known,
            extreme_ts=formed,
        )


def test_known_at_cannot_precede_formed_at() -> None:
    with pytest.raises(ValueError, match="known_at"):
        Zone("z", "EURUSD", ZoneKind.FVG, Direction.BULL, 1.0, 1.1, T0 + timedelta(hours=1), T0)


def test_identifiers_are_deterministic() -> None:
    zid = zone_id("EURUSD", ZoneKind.FVG, Direction.BULL, T0)
    assert zid == "EURUSD:FVG:BULL:20260105T090000Z"
    eid = event_id(zid, 0)
    assert eid == f"{zid}#0"
    assert candidate_id(eid, "sweep") == f"{zid}#0:sweep"
    assert make_run_id("a", "b", "c") == make_run_id("a", "b", "c")
    assert make_run_id("a", "b", "c") != make_run_id("a", "b", "d")


def test_order_intent_stop_must_be_on_the_losing_side() -> None:
    common = {
        "candidate_id": "c",
        "event_id": "e",
        "trigger": "sweep",
        "ts_decision": T0,
        "entry_policy": "market_next_open",
        "entry_ref": 1.0,
    }
    OrderIntent(side=Side.LONG, stop_price=0.9, **common)  # type: ignore[arg-type]
    OrderIntent(side=Side.SHORT, stop_price=1.1, **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OrderIntent(side=Side.LONG, stop_price=1.1, **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OrderIntent(side=Side.SHORT, stop_price=0.9, **common)  # type: ignore[arg-type]


def test_trade_validation() -> None:
    kwargs = {
        "trade_id": "t",
        "side": Side.LONG,
        "entry_ts": T0,
        "entry_fill": 1.0,
        "stop_price": 0.9,
        "exit_ts": T0 + timedelta(minutes=5),
        "exit_reason": ExitReason.TARGET,
        "exit_fill": 1.3,
        "r_net": 2.9,
        "mfe_r": 3.0,
        "mae_r": 0.2,
        "ambiguous_bars": 0,
        "cost_r": 0.1,
    }
    Trade(risk_distance=0.1, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Trade(risk_distance=0.0, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Trade(risk_distance=0.1, **{**kwargs, "exit_ts": T0 - timedelta(minutes=1)})  # type: ignore[arg-type]


def test_side_sign() -> None:
    assert Side.LONG.sign == 1
    assert Side.SHORT.sign == -1
