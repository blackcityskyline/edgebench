"""G5: the same input gives the same output, regardless of interpreter hash seed."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from edgebench.config.environment import SessionsConfig
from edgebench.config.schema import StrategyConfig
from edgebench.contracts import Bar
from edgebench.data.synthetic import make_m1
from edgebench.engine import run_engine
from edgebench.execution import CostModel

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[1]


def build_and_digest(seed: int = 5, minutes: int = 12_000) -> str:
    frame = make_m1(minutes, seed=seed, vol_bp=8.0)
    bars = [
        Bar(r.ts_open, r.open, r.high, r.low, r.close, r.volume, "M1")
        for r in frame.itertuples(index=False)
    ]
    cfg = StrategyConfig.model_validate(
        {
            "instruments": ["EURUSD"],
            "sessions": ["all"],
            "mode": "portfolio",
            "entry": {"max_stop_atr_h1": 3.0, "min_stop_spreads": 1.0, "combine": "all_of"},
            "zones": {"episode_gap_bars": 3},
        }
    )
    sessions = SessionsConfig.model_validate(
        {"sessions": {"all": {"start": "00:00", "end": "23:59"}}}
    )
    out = run_engine(cfg, "EURUSD", bars, CostModel(0.01, 0.005, 5.0), sessions)
    payload = repr((out.zones, out.events, out.candidates, out.trades, sorted(out.counts.items())))
    return hashlib.sha256(payload.encode()).hexdigest()


def test_two_runs_in_one_process_agree() -> None:
    assert build_and_digest() == build_and_digest()


def test_different_data_gives_different_output() -> None:
    assert build_and_digest(seed=5) != build_and_digest(seed=6)


def test_hash_seed_does_not_change_the_output() -> None:
    code = (
        "import sys; sys.path.insert(0, 'tests'); "
        "import test_determinism as t; print(t.build_and_digest())"
    )
    digests = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        digests.add(proc.stdout.strip())
    assert len(digests) == 1
    assert digests == {build_and_digest()}
