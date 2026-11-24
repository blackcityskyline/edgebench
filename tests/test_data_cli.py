import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from edgebench.cli import main
from edgebench.data.synthetic import make_m1

ROOT = Path(__file__).resolve().parent.parent


def load_tool(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"tool_{name}", ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


fetch_binance = load_tool("fetch_binance")


def write_klines(path: Path, minutes: int, seed: int) -> None:
    frame = make_m1(minutes, seed=seed)
    lines = []
    for row in frame.itertuples(index=False):
        ms = int(row.ts_open.timestamp() * 1000)
        lines.append(f"{ms},{row.open},{row.high},{row.low},{row.close},{row.volume},0,0,0,0,0,0")
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "splits.yaml").write_text(
        "holdout_fraction: 0.2\nembargo_days: 2\nwalk_forward_folds: 4\n"
    )
    monkeypatch.setenv("EDGEBENCH_ROOT", str(tmp_path))
    monkeypatch.setenv("EDGEBENCH_DATA", str(tmp_path / "data"))
    return tmp_path


def test_ingest_info_verify_gaps_and_split_freeze(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = workspace / "klines.csv"
    write_klines(raw, 100 * 1440, seed=1)
    assert (
        main(["data", "ingest", "--source", "binance", "--symbol", "BTCUSDT", "--files", str(raw)])
        == 0
    )
    out = capsys.readouterr().out
    assert "144000 M1 bars" in out and "price side trade" in out and "no gaps" in out

    assert (
        main(["data", "ingest", "--source", "binance", "--symbol", "BTCUSDT", "--files", str(raw)])
        == 0
    )
    assert main(["data", "info"]) == 0
    info = capsys.readouterr().out
    assert "binance/BTCUSDT: 144000 rows" in info and "data_version" in info

    assert main(["data", "verify"]) == 0
    assert main(["data", "gaps", "--source", "binance", "--symbol", "BTCUSDT"]) == 0
    assert "0 gaps" in capsys.readouterr().out

    assert main(["data", "split"]) == 0
    shown = capsys.readouterr().out
    assert "holdout  from 2024-03-21 (derived)" in shown
    assert main(["data", "split", "--write"]) == 0
    written = (workspace / "config" / "splits.yaml").read_text()
    assert "holdout_start: 2024-03-21" in written and "dev_end: 2024-03-19" in written
    assert main(["data", "split"]) == 0
    assert "frozen in config" in capsys.readouterr().out
    assert main(["data", "split", "--write"]) == 1  # a frozen boundary is never overwritten
    assert "already frozen" in capsys.readouterr().err


def test_conflicting_ingest_and_missing_data_fail_cleanly(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["data", "split"]) == 1
    assert "ingest data first" in capsys.readouterr().err
    first, second = workspace / "a.csv", workspace / "b.csv"
    write_klines(first, 50, seed=1)
    write_klines(second, 50, seed=2)  # same minutes, different prices
    assert (
        main(["data", "ingest", "--source", "binance", "--symbol", "X", "--files", str(first)]) == 0
    )
    assert (
        main(["data", "ingest", "--source", "binance", "--symbol", "X", "--files", str(second)])
        == 1
    )
    assert "conflicting" in capsys.readouterr().err
    assert (
        main(
            [
                "data",
                "ingest",
                "--source",
                "binance",
                "--symbol",
                "X",
                "--files",
                str(workspace / "no"),
            ]
        )
        == 1
    )


def test_ask_files_are_only_for_dukascopy(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = workspace / "k.csv"
    write_klines(raw, 10, seed=1)
    args = [
        "data",
        "ingest",
        "--source",
        "binance",
        "--symbol",
        "X",
        "--files",
        str(raw),
        "--ask-files",
        str(raw),
    ]
    assert main(args) == 1
    assert "only supported for dukascopy" in capsys.readouterr().err


def test_dukascopy_bid_and_ask_ingest(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bid, ask = workspace / "bid.csv", workspace / "ask.csv"
    frame = make_m1(30, seed=3)
    for path, shift in ((bid, 0.0), (ask, 0.0002)):
        rows = ["timestamp,open,high,low,close,volume"]
        for r in frame.itertuples(index=False):
            ms = int(r.ts_open.timestamp() * 1000)
            rows.append(
                f"{ms},{r.open + shift},{r.high + shift},{r.low + shift},{r.close + shift},1"
            )
        path.write_text("\n".join(rows) + "\n")
    args = [
        "data",
        "ingest",
        "--source",
        "dukascopy",
        "--symbol",
        "eurusd",
        "--files",
        str(bid),
        "--ask-files",
        str(ask),
    ]
    assert main(args) == 0
    assert "price side bid" in capsys.readouterr().out
    assert main(["data", "info"]) == 0
    assert "side ['bid'], ask" in capsys.readouterr().out


def test_previous_months_skips_the_current_month_and_crosses_years() -> None:
    today = datetime(2026, 2, 10, tzinfo=UTC)
    assert fetch_binance.previous_months(3, today) == ["2025-11", "2025-12", "2026-01"]
    assert fetch_binance.previous_months(1, datetime(2026, 1, 1, tzinfo=UTC)) == ["2025-12"]


def test_checksum_parsing() -> None:
    digest = "a" * 64
    assert fetch_binance.parse_checksum(f"{digest}  BTCUSDT-1m-2024-01.zip\n") == digest
    with pytest.raises(ValueError):
        fetch_binance.parse_checksum("not a checksum")
    with pytest.raises(ValueError):
        fetch_binance.parse_checksum("")


def test_download_month_verifies_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    payload = b"zip-bytes"
    digest = hashlib.sha256(payload).hexdigest()
    served = {
        "u.zip.CHECKSUM": f"{digest}  u.zip".encode(),
        "u.zip": payload,
    }
    calls: list[str] = []

    def fake_fetch(url: str) -> bytes | None:
        calls.append(url)
        return served.get(url.rsplit("/", 1)[-1].replace("BTCUSDT-1m-2024-01", "u"))

    monkeypatch.setattr(fetch_binance, "fetch", fake_fetch)
    assert fetch_binance.download_month("BTCUSDT", "2024-01", tmp_path) == "ok"
    assert (tmp_path / "BTCUSDT-1m-2024-01.zip").read_bytes() == payload
    calls.clear()
    assert fetch_binance.download_month("BTCUSDT", "2024-01", tmp_path) == "cached"
    assert len(calls) == 1  # only the checksum was requested
    served["u.zip"] = b"tampered"
    (tmp_path / "BTCUSDT-1m-2024-01.zip").unlink()
    with pytest.raises(ValueError, match="mismatch"):
        fetch_binance.download_month("BTCUSDT", "2024-01", tmp_path)
    assert not (tmp_path / "BTCUSDT-1m-2024-01.zip").exists()
    monkeypatch.setattr(fetch_binance, "fetch", lambda url: None)
    assert fetch_binance.download_month("BTCUSDT", "2020-01", tmp_path) == "missing"
