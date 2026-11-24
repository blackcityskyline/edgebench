"""Download Binance spot 1m kline archives from data.binance.vision (run on your own machine).

    python tools/fetch_binance.py BTCUSDT ETHUSDT SOLUSDT TONUSDT --months 48

Files go to data/raw/binance/<SYMBOL>/ (git-ignored) and are verified against the published
.CHECKSUM files. Existing verified files are skipped, so the command can be re-run to resume.
The current month is not available as a monthly archive and is skipped. Months before a symbol
was listed return 404 and are reported, not treated as errors.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

BASE = "https://data.binance.vision/data/spot/monthly/klines"
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "binance"
PAUSE_SECONDS = 0.2


def previous_months(count: int, today: datetime | None = None) -> list[str]:
    """The last ``count`` full months before ``today`` as ``YYYY-MM``, oldest first."""
    now = today or datetime.now(UTC)
    year, month = now.year, now.month
    months: list[str] = []
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        months.append(f"{year:04d}-{month:02d}")
    return months[::-1]


def parse_checksum(text: str) -> str:
    """The sha256 from a ``<hash>  <filename>`` checksum file."""
    token = text.split()[0].lower() if text.split() else ""
    if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
        raise ValueError(f"unexpected checksum file content: {text[:80]!r}")
    return token


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str) -> bytes | None:
    """GET ``url``; None on 404."""
    try:
        with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https host
            return bytes(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    finally:
        time.sleep(PAUSE_SECONDS)


def download_month(symbol: str, month: str, out_dir: Path) -> str:
    """Download one monthly archive. Returns ``ok``, ``cached`` or ``missing``."""
    name = f"{symbol}-1m-{month}.zip"
    target = out_dir / name
    url = f"{BASE}/{symbol}/1m/{name}"
    checksum_raw = fetch(url + ".CHECKSUM")
    if checksum_raw is None:
        return "missing"
    expected = parse_checksum(checksum_raw.decode("utf-8", errors="replace"))
    if target.exists() and sha256_of(target) == expected:
        return "cached"
    data = fetch(url)
    if data is None:
        return "missing"
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{name}: checksum mismatch, file not saved")
    out_dir.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(target)
    return "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Binance spot 1m kline archives")
    parser.add_argument("symbols", nargs="+", help="e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--months", type=int, default=48, help="how many full months back")
    parser.add_argument("--out", type=Path, default=RAW_DIR, help="output folder")
    args = parser.parse_args()
    months = previous_months(args.months)
    failed = False
    for symbol in args.symbols:
        counts = {"ok": 0, "cached": 0, "missing": 0}
        for month in months:
            try:
                counts[download_month(symbol.upper(), month, args.out / symbol.upper())] += 1
            except (OSError, ValueError) as exc:
                failed = True
                print(f"{symbol} {month}: {exc}", file=sys.stderr)
        print(
            f"{symbol}: {counts['ok']} downloaded, {counts['cached']} cached, "
            f"{counts['missing']} not available"
        )
        print(
            f"  next: edgebench data ingest --source binance --symbol {symbol.upper()} "
            f"--files {args.out / symbol.upper()}/*.zip"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
