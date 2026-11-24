from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from edgebench.data import (
    DataError,
    content_hash,
    data_version,
    normalize_m1,
    verify_store,
    write_m1,
)
from edgebench.data.store import dataset_range, load_manifest, parquet_path, read_raw_m1
from edgebench.data.synthetic import make_m1

NEW_YEAR_EVE = datetime(2023, 12, 31, 23, 0, tzinfo=UTC)


def test_roundtrip_across_a_year_boundary(tmp_path: Path) -> None:
    frame = make_m1(180, seed=1, start=NEW_YEAR_EVE)  # 23:00 to 01:59
    entries = write_m1(tmp_path, "binance", "BTCUSDT", frame, "trade")
    assert [e.year for e in entries] == [2023, 2024]
    assert [e.rows for e in entries] == [60, 120]
    assert parquet_path(tmp_path, "binance", "BTCUSDT", 2023).exists()
    back = read_raw_m1(tmp_path, "binance", "BTCUSDT")
    pd.testing.assert_frame_equal(back, frame, check_exact=True)
    first, last = dataset_range(tmp_path, "binance", "BTCUSDT")
    assert first == frame["ts_open"].iloc[0] and last == frame["ts_open"].iloc[-1]


def test_read_range_is_half_open(tmp_path: Path) -> None:
    frame = make_m1(120, seed=1)
    write_m1(tmp_path, "binance", "BTCUSDT", frame, "trade")
    start = pd.Timestamp("2024-01-01 00:30", tz="UTC")
    end = pd.Timestamp("2024-01-01 01:00", tz="UTC")
    part = read_raw_m1(tmp_path, "binance", "BTCUSDT", start=start, end=end)
    assert len(part) == 30
    assert part["ts_open"].iloc[0] == start and part["ts_open"].iloc[-1] < end


def test_rewriting_the_same_data_is_idempotent_and_appending_merges(tmp_path: Path) -> None:
    frame = make_m1(300, seed=2)
    write_m1(tmp_path, "binance", "BTCUSDT", frame.iloc[:200], "trade")
    version_a = data_version(tmp_path)
    write_m1(tmp_path, "binance", "BTCUSDT", frame.iloc[:200], "trade")
    assert data_version(tmp_path) == version_a
    write_m1(tmp_path, "binance", "BTCUSDT", frame.iloc[100:], "trade")  # overlaps 100 rows
    pd.testing.assert_frame_equal(read_raw_m1(tmp_path, "binance", "BTCUSDT"), frame)
    assert data_version(tmp_path) != version_a


def test_conflicting_minutes_are_refused(tmp_path: Path) -> None:
    frame = make_m1(10, seed=2)
    write_m1(tmp_path, "binance", "BTCUSDT", frame, "trade")
    changed = frame.copy()
    changed.loc[3, "close"] = changed.loc[3, "close"] + 0.001
    changed.loc[3, "high"] = changed.loc[3, "high"] + 1.0
    with pytest.raises(DataError, match="conflicting"):
        write_m1(tmp_path, "binance", "BTCUSDT", changed, "trade")


def test_invalid_input_is_refused(tmp_path: Path) -> None:
    frame = make_m1(10, seed=2)
    with pytest.raises(DataError, match="price_side"):
        write_m1(tmp_path, "binance", "BTCUSDT", frame, "last")
    broken = frame.copy()
    broken.loc[2, "high"] = broken.loc[2, "low"] - 1.0
    with pytest.raises(DataError, match="invalid"):
        write_m1(tmp_path, "binance", "BTCUSDT", broken, "trade")
    with pytest.raises(DataError, match="no data"):
        read_raw_m1(tmp_path, "binance", "ETHUSDT")


def test_manifest_records_content_and_ask_flag(tmp_path: Path) -> None:
    frame = make_m1(60, seed=4, ask_spread=0.1)
    write_m1(tmp_path, "dukascopy", "eurusd", frame, "bid")
    (entry,) = load_manifest(tmp_path).values()
    assert entry["rows"] == 60 and entry["has_ask"] is True and entry["price_side"] == "bid"
    assert entry["content_sha256"] == content_hash(normalize_m1(frame))
    assert len(entry["sha256"]) == 64


def test_verify_store_detects_tampering(tmp_path: Path) -> None:
    write_m1(tmp_path, "binance", "BTCUSDT", make_m1(60, seed=5), "trade")
    assert verify_store(tmp_path) == []
    path = parquet_path(tmp_path, "binance", "BTCUSDT", 2024)
    other = make_m1(60, seed=6)
    other.to_parquet(path, index=False)
    problems = " ".join(verify_store(tmp_path))
    assert "file hash differs" in problems and "content hash differs" in problems
    path.unlink()
    assert "file is missing" in " ".join(verify_store(tmp_path))


def test_data_version_can_be_limited_to_the_datasets_a_run_uses(tmp_path: Path) -> None:
    write_m1(tmp_path, "binance", "BTCUSDT", make_m1(60, seed=1), "trade")
    only_btc = data_version(tmp_path, [("binance", "BTCUSDT")])
    write_m1(tmp_path, "binance", "ETHUSDT", make_m1(60, seed=2), "trade")
    assert data_version(tmp_path, [("binance", "BTCUSDT")]) == only_btc
    assert data_version(tmp_path) != only_btc


def test_content_hash_is_deterministic_and_sensitive() -> None:
    a = make_m1(30, seed=1)
    assert content_hash(a) == content_hash(make_m1(30, seed=1))
    assert content_hash(a) != content_hash(make_m1(30, seed=2))
    b = a.copy()
    b.loc[0, "volume"] = b.loc[0, "volume"] + 1.0
    assert content_hash(a) != content_hash(b)
