from datetime import UTC, datetime

import pandas as pd
import pytest

from edgebench.data import DataError, resample
from edgebench.data.synthetic import frame_from_ohlc, make_m1

START = datetime(2024, 1, 1, tzinfo=UTC)

SIX = [
    (10.0, 12.0, 9.0, 11.0),  # 00:00
    (11.0, 15.0, 10.5, 14.0),  # 00:01
    (14.0, 14.5, 8.0, 9.0),  # 00:02
    (9.0, 9.5, 7.0, 8.0),  # 00:03
    (8.0, 13.0, 7.5, 12.0),  # 00:04
    (12.0, 12.5, 11.0, 11.5),  # 00:05
]


def test_m3_known_answer() -> None:
    out = resample(frame_from_ohlc(SIX, volume=2.0), "M3")
    assert len(out) == 2
    first, second = out.iloc[0], out.iloc[1]
    assert (first["open"], first["high"], first["low"], first["close"]) == (10.0, 15.0, 8.0, 9.0)
    assert (second["open"], second["high"], second["low"], second["close"]) == (
        9.0,
        13.0,
        7.0,
        11.5,
    )
    assert first["volume"] == 6.0 and first["n_m1"] == 3
    assert first["ts_open"] == pd.Timestamp("2024-01-01 00:00", tz="UTC")
    assert second["ts_open"] == pd.Timestamp("2024-01-01 00:03", tz="UTC")
    assert out["complete"].tolist() == [True, True]


def test_partial_bucket_is_flagged_incomplete_and_threshold_is_respected() -> None:
    frame = frame_from_ohlc(SIX).iloc[:5]  # last M3 bucket has 2 of 3 minutes
    default = resample(frame, "M3")
    assert default["complete"].tolist() == [True, False]
    assert default["n_m1"].tolist() == [3, 2]
    relaxed = resample(frame, "M3", min_m1_fraction=0.5)
    assert relaxed["complete"].tolist() == [True, True]


def test_open_and_close_come_from_first_and_last_available_minute() -> None:
    frame = frame_from_ohlc(SIX).iloc[[0, 2]].reset_index(drop=True)  # minute 1 is missing
    out = resample(frame, "M3")
    assert out["open"].iloc[0] == 10.0 and out["close"].iloc[0] == 9.0
    assert out["n_m1"].iloc[0] == 2
    assert not out["complete"].iloc[0]


def test_h1_is_aligned_to_the_clock_and_flags_a_half_hour_start() -> None:
    start = datetime(2024, 1, 1, 0, 30, tzinfo=UTC)
    frame = make_m1(150, seed=1, start=start)  # 00:30 to 02:59
    out = resample(frame, "H1")
    assert out["ts_open"].tolist() == [
        pd.Timestamp("2024-01-01 00:00", tz="UTC"),
        pd.Timestamp("2024-01-01 01:00", tz="UTC"),
        pd.Timestamp("2024-01-01 02:00", tz="UTC"),
    ]
    assert out["n_m1"].tolist() == [30, 60, 60]
    assert out["complete"].tolist() == [False, True, True]


def test_h1_matches_m1_extremes() -> None:
    frame = make_m1(120, seed=3)
    out = resample(frame, "H1")
    assert out["high"].iloc[0] == frame["high"].iloc[:60].max()
    assert out["low"].iloc[1] == frame["low"].iloc[60:].min()
    assert out["close"].iloc[0] == frame["close"].iloc[59]
    assert out["volume"].iloc[0] == pytest.approx(frame["volume"].iloc[:60].sum())


def test_m1_passthrough_and_ask_columns() -> None:
    frame = make_m1(6, seed=2, ask_spread=0.05)
    same = resample(frame, "M1")
    assert same["n_m1"].tolist() == [1] * 6 and same["complete"].all()
    m3 = resample(frame, "M3")
    assert m3["ask_close"].iloc[0] == pytest.approx(frame["close"].iloc[2] + 0.05)
    assert m3["ask_high"].iloc[0] == pytest.approx(frame["high"].iloc[:3].max() + 0.05)


def test_invalid_input_is_rejected() -> None:
    frame = frame_from_ohlc(SIX)
    with pytest.raises(DataError, match="timeframe"):
        resample(frame, "M5")
    with pytest.raises(DataError, match="min_m1_fraction"):
        resample(frame, "M3", min_m1_fraction=0.0)
    with pytest.raises(DataError, match="sorted"):
        resample(frame.iloc[::-1], "M3")
