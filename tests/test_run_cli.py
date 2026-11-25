"""``edgebench run`` end to end on a synthetic store in a temporary repository."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from edgebench.cli import build_parser
from edgebench.data.store import write_m1
from edgebench.data.synthetic import make_m1

pytestmark = pytest.mark.slow
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(ROOT / "config", tmp_path / "config")
    cfg = yaml.safe_load((tmp_path / "config" / "strategy_v1.yaml").read_text())
    cfg["instruments"] = ["EURUSD"]
    cfg["sessions"] = ["london"]
    cfg["entry"]["max_stop_atr_h1"] = 3.0
    cfg["entry"]["min_stop_spreads"] = 1.0
    cfg["patterns"]["baseline"] = {"enabled": True, "probability": 0.2}  # also in strategy_v1
    (tmp_path / "config" / "strategy_v1.yaml").write_text(yaml.safe_dump(cfg))
    sessions = {
        "tz": "America/New_York",
        "sessions": {"london": {"start": "00:00", "end": "23:59"}},
    }
    (tmp_path / "config" / "sessions.yaml").write_text(yaml.safe_dump(sessions))
    data = tmp_path / "data"
    write_m1(data, "dukascopy", "eurusd", make_m1(70 * 24 * 60, seed=2, vol_bp=8.0), "bid")
    monkeypatch.setenv("EDGEBENCH_ROOT", str(tmp_path))
    monkeypatch.setenv("EDGEBENCH_DATA", str(data))
    monkeypatch.delenv("EDGEBENCH_HOLDOUT_TOKEN", raising=False)
    return tmp_path


def run(*argv: str) -> int:
    args = build_parser().parse_args(["run", *argv])
    return int(args.func(args))


def test_run_writes_report_manifest_ledger_and_tables(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("--instruments", "EURUSD") == 0
    run_dirs = [p for p in (repo / "runs").iterdir() if p.is_dir()]
    assert len(run_dirs) == 1
    report = (run_dirs[0] / "report.md").read_text()
    assert "## By trigger" in report and "baseline" in report and "trials so far: 1" in report
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["split"] == "dev" and manifest["instruments"] == ["EURUSD"]
    assert (repo / "data" / "runs" / run_dirs[0].name / "candidates.parquet").exists()
    lines = (repo / "runs" / "ledger.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["run_id"] == manifest["run_id"]
    # the same configuration again: the run is recorded again but is not a new trial
    assert run() == 0
    assert len((repo / "runs" / "ledger.jsonl").read_text().splitlines()) == 2
    assert "trials so far: 1" in (run_dirs[0] / "report.md").read_text()
    assert "events" in capsys.readouterr().out
    # charts from the stored tables (needs matplotlib)
    pytest.importorskip("matplotlib")
    from edgebench.cli import build_parser as bp

    shots = repo / "shots"
    args = bp().parse_args(
        ["chart", "--run", run_dirs[0].name[:6], "--sample", "2", "--blind", "--out", str(shots)]
    )
    assert args.func(args) == 0
    assert len(list(shots.glob("*.png"))) == 2


def test_holdout_needs_a_reason_and_the_owner_token(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run("--split", "holdout") == 1
    assert run("--split", "holdout", "--holdout-reason", "test") == 1
    assert "EDGEBENCH_HOLDOUT_TOKEN" in capsys.readouterr().err
    assert not (repo / "holdout" / "ledger.jsonl").exists()
