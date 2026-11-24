import json
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import pytest

from edgebench.config import SplitsConfig
from edgebench.contracts import Bar
from edgebench.data import (
    DataError,
    HoldoutDenied,
    HoldoutRequest,
    authorize_holdout,
    derive_bounds,
    iter_bars,
    load_bars,
    load_m1,
    write_m1,
)
from edgebench.data.holdout import TOKEN_ENV, read_ledger
from edgebench.data.splits import SplitBounds
from edgebench.data.synthetic import frame_from_ohlc, make_m1

DAYS = 100


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, SplitBounds]:
    root = tmp_path_factory.mktemp("store")
    frame = make_m1(DAYS * 1440, seed=7)
    write_m1(root, "binance", "BTCUSDT", frame, "trade")
    cfg = SplitsConfig(holdout_fraction=0.2, embargo_days=2, walk_forward_folds=4)
    last_end = frame["ts_open"].iloc[-1].to_pydatetime() + pd.Timedelta(minutes=1)
    return root, derive_bounds(frame["ts_open"].iloc[0].to_pydatetime(), last_end, cfg)


def request(tmp_path: Path, reason: str = "final check of v1") -> HoldoutRequest:
    return HoldoutRequest(reason, "cfg123", "abc1234", tmp_path / "ledger.jsonl")


def test_dev_split_stops_before_the_embargo(store: tuple[Path, SplitBounds]) -> None:
    root, bounds = store
    dev = load_m1(root, "binance", "BTCUSDT", bounds)
    assert dev["ts_open"].iloc[0] == pd.Timestamp(bounds.dev_start)
    assert dev["ts_open"].iloc[-1] < pd.Timestamp(bounds.dev_end)
    assert dev["ts_open"].iloc[-1] == pd.Timestamp(bounds.dev_end) - pd.Timedelta(minutes=1)


def test_holdout_needs_a_request_and_the_token(
    store: tuple[Path, SplitBounds], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, bounds = store
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    with pytest.raises(DataError, match="HoldoutRequest"):
        load_m1(root, "binance", "BTCUSDT", bounds, split="holdout")
    with pytest.raises(HoldoutDenied, match=TOKEN_ENV):
        load_m1(root, "binance", "BTCUSDT", bounds, "holdout", request(tmp_path))
    assert read_ledger(tmp_path / "ledger.jsonl") == []  # a denied attempt leaves no data access


def test_holdout_with_token_is_logged_and_disjoint_from_dev(
    store: tuple[Path, SplitBounds], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, bounds = store
    monkeypatch.setenv(TOKEN_ENV, "owner")
    holdout = load_m1(root, "binance", "BTCUSDT", bounds, "holdout", request(tmp_path))
    dev = load_m1(root, "binance", "BTCUSDT", bounds)
    assert holdout["ts_open"].iloc[0] == pd.Timestamp(bounds.holdout_start)
    gap = holdout["ts_open"].iloc[0] - dev["ts_open"].iloc[-1]
    assert gap >= pd.Timedelta(days=bounds.embargo_days)
    (record,) = read_ledger(tmp_path / "ledger.jsonl")
    assert record["reason"] == "final check of v1" and record["config_hash"] == "cfg123"


def test_authorize_requires_a_reason_and_appends_lines(tmp_path: Path) -> None:
    ledger = tmp_path / "holdout" / "ledger.jsonl"
    env = {TOKEN_ENV: "owner"}
    with pytest.raises(HoldoutDenied, match="reason"):
        authorize_holdout(ledger, "  ", "c", "g", environ=env)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    authorize_holdout(ledger, "first", "c", "g", environ=env, now=now)
    authorize_holdout(ledger, "second", "c", "g", environ=env, now=now)
    lines = ledger.read_text().splitlines()
    assert [json.loads(line)["reason"] for line in lines] == ["first", "second"]
    with pytest.raises(HoldoutDenied):
        authorize_holdout(ledger, "third", "c", "g", environ={TOKEN_ENV: ""})
    assert len(ledger.read_text().splitlines()) == 2


def test_load_bars_and_iter_bars(store: tuple[Path, SplitBounds]) -> None:
    root, bounds = store
    h1 = load_bars(root, "binance", "BTCUSDT", bounds, "H1")
    assert h1["complete"].all()
    bars = list(iter_bars(h1.iloc[:3], "H1"))
    assert all(isinstance(bar, Bar) for bar in bars)
    assert bars[0].ts_close == bars[1].ts_open
    assert bars[0].complete


def test_iter_bars_carries_the_incomplete_flag() -> None:
    frame = frame_from_ohlc([(1.0, 1.2, 0.9, 1.1)] * 4).iloc[:4]
    from edgebench.data import resample

    m3 = resample(frame, "M3")  # second bucket holds one minute of three
    assert [bar.complete for bar in iter_bars(m3, "M3")] == [True, False]


def test_explicit_frozen_split_is_used(store: tuple[Path, SplitBounds]) -> None:
    root, _ = store
    cfg = SplitsConfig(
        holdout_fraction=0.2,
        embargo_days=2,
        walk_forward_folds=4,
        holdout_start=date(2024, 3, 1),
    )
    bounds = derive_bounds(datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 4, 10, tzinfo=UTC), cfg)
    dev = load_m1(root, "binance", "BTCUSDT", bounds)
    assert dev["ts_open"].iloc[-1] < pd.Timestamp("2024-02-28", tz="UTC")
