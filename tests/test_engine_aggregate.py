from datetime import UTC, datetime, timedelta

import pandas as pd

from edgebench.contracts import Bar
from edgebench.data.resample import resample
from edgebench.data.synthetic import make_m1
from edgebench.engine.aggregate import Aggregator

T0 = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
MIN = timedelta(minutes=1)


def m1(i: int, o: float = 1.0, h: float = 2.0, lo: float = 0.5, c: float = 1.5) -> Bar:
    return Bar(T0 + i * MIN, o, h, lo, c, 1.0, "M1")


def test_m3_is_emitted_when_its_last_minute_closes() -> None:
    agg = Aggregator("M3")
    assert agg.push(m1(0, o=1.0, h=2.0, lo=0.8, c=1.1)) == []
    assert agg.push(m1(1, h=3.0, lo=0.9)) == []
    out = agg.push(m1(2, c=1.7))
    assert len(out) == 1
    bar = out[0]
    assert (bar.ts_open, bar.tf, bar.complete) == (T0, "M3", True)
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (1.0, 3.0, 0.5, 1.7, 3.0)
    assert bar.ts_close == T0 + 3 * MIN


def test_a_missing_last_minute_emits_when_a_later_bucket_starts() -> None:
    agg = Aggregator("M3", min_m1_fraction=0.6)
    agg.push(m1(0))
    assert agg.push(m1(1)) == []
    out = agg.push(m1(3))  # minute 2 is missing; bucket 10:03 begins
    assert len(out) == 1 and out[0].complete  # 2 of 3 minutes >= 0.6


def test_sparse_buckets_are_flagged_incomplete() -> None:
    agg = Aggregator("M3")  # min fraction 0.8: 2 of 3 is not enough
    agg.push(m1(0))
    agg.push(m1(1))
    out = agg.push(m1(3))
    assert len(out) == 1 and not out[0].complete


def test_matches_batch_resample_on_synthetic_data() -> None:
    frame = make_m1(600, seed=3, weekends=True)
    bars = [
        Bar(r.ts_open, r.open, r.high, r.low, r.close, r.volume, "M1")
        for r in frame.itertuples(index=False)
    ]
    for tf in ("M3", "H1"):
        agg = Aggregator(tf)
        streamed = [b for bar in bars for b in agg.push(bar)]
        batch = resample(frame, tf)
        assert len(streamed) == len(batch)
        for got, (_, want) in zip(streamed, batch.iterrows(), strict=True):
            assert pd.Timestamp(got.ts_open) == want["ts_open"]
            assert (got.open, got.high, got.low, got.close) == (
                want["open"], want["high"], want["low"], want["close"],
            )  # fmt: skip
            assert got.complete == bool(want["complete"])
