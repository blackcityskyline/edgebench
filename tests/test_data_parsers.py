import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from edgebench.data import (
    DataError,
    find_gaps,
    merge_ask,
    normalize_m1,
    parse_binance_klines,
    parse_dukascopy_csv,
    validate_m1,
)
from edgebench.data.parsers import detect_epoch_unit, epoch_to_utc
from edgebench.data.synthetic import frame_from_ohlc

T_2024 = 1704067200  # 2024-01-01T00:00:00Z
T_2025 = 1735689600  # 2025-01-01T00:00:00Z

BINANCE_TAIL = ",0,0,0,0,0,0"


def kline(ts: int, o: float, h: float, low: float, c: float, v: float) -> str:
    return f"{ts},{o},{h},{low},{c},{v}{BINANCE_TAIL}\n"


def test_binance_milliseconds() -> None:
    text = kline(T_2024 * 1000, 1, 2, 0.5, 1.5, 10) + kline(
        (T_2024 + 60) * 1000, 1.5, 2.5, 1, 2, 11
    )
    frame = parse_binance_klines(io.StringIO(text))
    assert list(frame["ts_open"]) == [
        pd.Timestamp("2024-01-01 00:00", tz="UTC"),
        pd.Timestamp("2024-01-01 00:01", tz="UTC"),
    ]
    assert frame["close"].tolist() == [1.5, 2.0]
    assert str(frame["ts_open"].dtype) == "datetime64[ns, UTC]"


def test_binance_microseconds_after_2025() -> None:
    frame = parse_binance_klines(io.StringIO(kline(T_2025 * 1_000_000, 1, 2, 0.5, 1.5, 10)))
    assert frame["ts_open"].iloc[0] == pd.Timestamp("2025-01-01", tz="UTC")


def test_binance_header_row_is_skipped() -> None:
    header = "open_time,open,high,low,close,volume,close_time,q,n,tb,tq,i\n"
    frame = parse_binance_klines(io.StringIO(header + kline(T_2024 * 1000, 1, 2, 0.5, 1.5, 10)))
    assert len(frame) == 1


def test_binance_zip_file(tmp_path: Path) -> None:
    path = tmp_path / "BTCUSDT-1m-2024-01.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("BTCUSDT-1m-2024-01.csv", kline(T_2024 * 1000, 1, 2, 0.5, 1.5, 10))
    assert len(parse_binance_klines(path)) == 1


def test_epoch_unit_detection_and_range_check() -> None:
    assert detect_epoch_unit(pd.Series([T_2024])) == "s"
    assert detect_epoch_unit(pd.Series([T_2024 * 1000])) == "ms"
    assert detect_epoch_unit(pd.Series([T_2024 * 10**6])) == "us"
    assert detect_epoch_unit(pd.Series([T_2024 * 10**9])) == "ns"
    with pytest.raises(DataError, match="outside"):
        epoch_to_utc(pd.Series([5, 6]))
    with pytest.raises(DataError):
        detect_epoch_unit(pd.Series(["x", "y"]))


def test_dukascopy_epoch_and_iso_timestamps() -> None:
    epoch = "timestamp,open,high,low,close,volume\n1704067200000,1,2,0.5,1.5,10\n"
    iso = "time,Open,High,Low,Close\n2024-01-01T00:00:00Z,1,2,0.5,1.5\n"
    a = parse_dukascopy_csv(io.StringIO(epoch))
    b = parse_dukascopy_csv(io.StringIO(iso))
    assert a["ts_open"].iloc[0] == b["ts_open"].iloc[0] == pd.Timestamp("2024-01-01", tz="UTC")
    assert b["volume"].iloc[0] == 0.0
    with pytest.raises(DataError, match="timestamp"):
        parse_dukascopy_csv(io.StringIO("open,high,low,close\n1,2,0.5,1.5\n"))
    with pytest.raises(DataError, match="price"):
        parse_dukascopy_csv(io.StringIO("timestamp,open\n1704067200000,1\n"))


def test_merge_ask_keeps_bid_rows_and_leaves_nan_for_missing_minutes() -> None:
    bid = frame_from_ohlc([(1.0, 1.2, 0.9, 1.1), (1.1, 1.3, 1.0, 1.2)])
    ask = frame_from_ohlc([(1.1, 1.3, 1.0, 1.2)])  # only the first minute
    merged = merge_ask(bid, ask)
    assert len(merged) == 2
    assert merged["ask_close"].tolist()[0] == 1.2
    assert pd.isna(merged["ask_close"].iloc[1])


def test_duplicates_identical_are_dropped_and_conflicts_raise() -> None:
    frame = frame_from_ohlc([(1.0, 1.2, 0.9, 1.1), (1.1, 1.3, 1.0, 1.2)])
    assert len(normalize_m1(pd.concat([frame, frame.iloc[:1]]))) == 2
    clash = frame.iloc[:1].copy()
    clash["close"] = 1.15
    with pytest.raises(DataError, match="conflicting"):
        normalize_m1(pd.concat([frame, clash]))


def test_validate_m1_reports_each_problem() -> None:
    good = frame_from_ohlc([(1.0, 1.2, 0.9, 1.1)])
    assert validate_m1(good) == []
    bad = good.copy()
    bad.loc[0, "high"] = 0.5  # below low, open and close
    problems = " ".join(validate_m1(bad))
    assert "high < low" in problems and "high below open/close" in problems
    negative = good.copy()
    negative.loc[0, "volume"] = -1.0
    assert "negative volume" in " ".join(validate_m1(negative))
    nan = good.copy()
    nan.loc[0, "open"] = float("nan")
    assert "non-finite" in " ".join(validate_m1(nan))
    assert validate_m1(good.iloc[0:0]) == ["frame is empty"]


def test_find_gaps_known_answer() -> None:
    frame = frame_from_ohlc([(1.0, 1.2, 0.9, 1.1)] * 6)
    frame = frame.iloc[[0, 1, 5]].reset_index(drop=True)  # minutes 0, 1, 5
    gaps = find_gaps(frame)
    assert len(gaps) == 1
    assert gaps["start"].iloc[0] == pd.Timestamp("2024-01-01 00:02", tz="UTC")
    assert gaps["end"].iloc[0] == pd.Timestamp("2024-01-01 00:05", tz="UTC")
    assert gaps["missing_minutes"].iloc[0] == 3
    assert find_gaps(frame, min_missing_minutes=4).empty
