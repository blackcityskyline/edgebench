from pathlib import Path

import pandas as pd
import pytest

from edgebench.chart import render_candidate, visible_bars
from edgebench.data.synthetic import make_m1

pytest.importorskip("matplotlib")


def test_blind_view_contains_only_bars_closed_by_the_decision() -> None:
    m1 = make_m1(600, seed=1)
    touch = m1["ts_open"].iloc[300] + pd.Timedelta(minutes=1)
    decision = m1["ts_open"].iloc[310] + pd.Timedelta(minutes=1)  # close of bar 310
    blind = visible_bars(m1, touch, decision, blind=True)
    assert blind["ts_open"].iloc[-1] == m1["ts_open"].iloc[310]
    assert blind["ts_open"].iloc[0] == m1["ts_open"].iloc[181]  # 120 minutes before the touch
    full = visible_bars(m1, touch, decision, blind=False)
    assert full["ts_open"].iloc[-1] == m1["ts_open"].iloc[310 + 150]
    assert len(full) > len(blind)


def test_render_writes_a_png_in_both_modes(tmp_path: Path) -> None:
    m1 = make_m1(600, seed=1)
    touch = m1["ts_open"].iloc[300] + pd.Timedelta(minutes=1)
    decision = m1["ts_open"].iloc[310] + pd.Timedelta(minutes=1)
    price = float(m1["close"].iloc[310])
    cand = pd.Series(
        {
            "candidate_id": "EURUSD:FVG:BULL:x#0:rejection", "instrument": "EURUSD", "side": "LONG",
            "trigger": "rejection", "session": "london", "ts_decision": decision,
            "touch_start": touch,
            "entry_ref": price, "stop_price": price - 0.2, "zone_low": price - 0.5,
            "zone_high": price - 0.1, "zone_known_at": touch - pd.Timedelta(minutes=90),
            "traded": True, "entry_fill": price + 0.01, "risk_distance": 0.21, "r_ref": 2.0,
            "exit_reason": "TARGET",
        }
    )  # fmt: skip
    obs = pd.DataFrame([{"detector": "rejection", "ts_decision": decision}])
    for blind in (True, False):
        bars = visible_bars(m1, touch, decision, blind)
        path = render_candidate(bars, cand, obs, tmp_path / f"c{blind}.png", blind=blind)
        assert path.read_bytes()[:4] == b"\x89PNG"
    with pytest.raises(ValueError, match="no bars"):
        render_candidate(m1.head(0), cand, obs, tmp_path / "x.png")
