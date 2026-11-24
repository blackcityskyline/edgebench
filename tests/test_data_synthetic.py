from datetime import UTC, datetime

import pandas as pd
import pytest

from edgebench.data import validate_m1
from edgebench.data.synthetic import frame_from_ohlc, make_m1


def test_same_seed_gives_the_same_frame_and_different_seeds_differ() -> None:
    pd.testing.assert_frame_equal(make_m1(500, seed=3), make_m1(500, seed=3), check_exact=True)
    assert not make_m1(500, seed=3)["close"].equals(make_m1(500, seed=4)["close"])


def test_generated_frames_are_valid_and_continuous() -> None:
    frame = make_m1(2000, seed=1, vol_bp=5.0)
    assert validate_m1(frame) == []
    assert frame["open"].iloc[1:].tolist() == pytest.approx(frame["close"].iloc[:-1].tolist())
    assert (frame["ts_open"].diff().dropna() == pd.Timedelta(minutes=1)).all()


def test_weekends_are_removed_when_requested() -> None:
    start = datetime(2024, 1, 5, tzinfo=UTC)  # a Friday
    frame = make_m1(4 * 1440, seed=1, start=start, weekends=True)
    assert set(frame["ts_open"].dt.day_of_week) == {4, 0}  # Friday and Monday only
    assert len(frame) == 2 * 1440


def test_ask_columns_follow_bid_plus_spread() -> None:
    frame = make_m1(50, seed=1, ask_spread=0.25)
    assert (frame["ask_close"] - frame["close"]).tolist() == pytest.approx([0.25] * 50)


def test_frame_from_ohlc_known_timestamps() -> None:
    frame = frame_from_ohlc([(1, 2, 0.5, 1.5), (1.5, 2.5, 1, 2)])
    assert frame["ts_open"].tolist() == [
        pd.Timestamp("2024-01-01 00:00", tz="UTC"),
        pd.Timestamp("2024-01-01 00:01", tz="UTC"),
    ]
    with pytest.raises(ValueError):
        frame_from_ohlc([])
    with pytest.raises(ValueError):
        make_m1(0)
