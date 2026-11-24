"""Download Dukascopy daily M1 candle archives for one instrument (run on your own machine).

The documented ``dukascopy-node`` CLI is not usable from this workspace: its JSON endpoint
(``jetta.dukascopy.com``) answers a plain HTTP 403 and the WAF recovery path does not apply. The
same Dukascopy daily candle archive is still published as ``<SIDE>_candles_min_1.bi5`` under
``datafeed.dukascopy.com``; this script reads that archive and writes one CSV per side in the
format ``edgebench data ingest`` expects (``timestamp,open,high,low,close,volume``, UTC).

    python tools/fetch_dukascopy.py --symbol EURUSD \
        --from 2022-11-01 --to 2026-11-01 --side both \
        --dir data/raw/dukascopy

Daily ``.bi5`` files are cached under ``<dir>/<symbol>-<side>/days/`` so a re-run resumes. Days
without a file (weekends, holidays) are listed in ``missing.txt`` and are kept as gaps, never
filled. ``--to`` is exclusive, matching ``dukascopy-node``.

Archive format (one 24-byte big-endian record per minute):
    uint32 seconds from 00:00 UTC, uint32 open, uint32 close, uint32 low, uint32 high,
    float32 volume, prices as integer points (``--point``, default 1e-5 for EURUSD).
Records with zero volume are Dukascopy's flat fillers and are dropped, like ``dukascopy-node``
without ``-fl``. The archive URL uses a zero-based month (``2022/10/01`` is 1 November 2022).
"""

from __future__ import annotations

import argparse
import http.client
import lzma
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

BASE = "https://datafeed.dukascopy.com/datafeed"
HOST = "datafeed.dukascopy.com"
RECORD_BYTES = 24
CACHE_QUERY = "v=edgebench"  # a query string bypasses a stale cached 503 from this host
SIDES = ("BID", "ASK")
USER_AGENT = "Mozilla/5.0"
_local = threading.local()


def archive_url(symbol: str, day: date, side: str) -> str:
    """URL of one daily candle archive. The archive month is zero-based."""
    return (
        f"{BASE}/{symbol.upper()}/"
        f"{day.year:04d}/{day.month - 1:02d}/{day.day:02d}/"
        f"{side.upper()}_candles_min_1.bi5?{CACHE_QUERY}"
    )


def decode_records(payload: bytes) -> list[tuple[int, int, int, int, int, float]]:
    """Decode one ``.bi5`` day into (seconds, open, close, low, high, volume) records."""
    raw = lzma.decompress(payload)
    if len(raw) % RECORD_BYTES:
        raise ValueError(f"decoded {len(raw)} bytes, not a multiple of {RECORD_BYTES}")
    return [
        struct.unpack(">IIIIIf", raw[offset : offset + RECORD_BYTES])
        for offset in range(0, len(raw), RECORD_BYTES)
    ]


def csv_rows(day: date, records: list[tuple[int, int, int, int, int, float]], point: float) -> str:
    """CSV lines for the live minutes of one day (flat zero-volume fillers are dropped)."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    lines: list[str] = []
    for seconds, open_px, close_px, low_px, high_px, volume in records:
        if volume <= 0:
            continue
        stamp = int((start + timedelta(seconds=seconds)).timestamp() * 1000)
        prices = (open_px * point, high_px * point, low_px * point, close_px * point)
        lines.append(
            f"{stamp},{prices[0]:.6f},{prices[1]:.6f},{prices[2]:.6f},{prices[3]:.6f},{volume}\n"
        )
    return "".join(lines)


def _connection() -> http.client.HTTPSConnection:
    """One keep-alive connection per thread.

    Opening a fresh TLS connection per day costs seconds against this host and mostly fails; a
    reused connection downloads a day in about a second.
    """
    conn: http.client.HTTPSConnection | None = getattr(_local, "conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(HOST, timeout=60)
        _local.conn = conn
    return conn


def _drop_connection() -> None:
    """Close this thread's connection after an error so the next attempt reconnects."""
    conn: http.client.HTTPSConnection | None = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def fetch_bytes(url: str, attempts: int = 5) -> bytes | None:
    """GET ``url``; None for 404. Retries 429, 503 and dropped connections with a pause."""
    parts = urlsplit(url)
    target = f"{parts.path}?{parts.query}"
    for attempt in range(attempts):
        try:
            conn = _connection()
            conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            response = conn.getresponse()
            body = response.read()
            if response.status == 200:
                return body
            if response.status == 404:
                return None
            if response.status not in (429, 503):
                raise RuntimeError(f"HTTP {response.status} for {url}")
        except (OSError, http.client.HTTPException):
            pass
        _drop_connection()
        time.sleep(1 + attempt)
    return b""


def download_day(symbol: str, day: date, side: str, target: Path) -> str:
    """Download and cache one day. Returns ``ok``, ``cached``, ``missing`` or ``failed``."""
    if target.exists() and target.stat().st_size:
        return "cached"
    payload = fetch_bytes(archive_url(symbol, day, side))
    if payload is None:
        return "missing"
    if not payload:
        return "failed"
    try:
        decode_records(payload)  # a proxy error page is not a candle archive
    except (lzma.LZMAError, ValueError):
        return "failed"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    return "ok"


def merge(side_dir: Path, symbol: str, side: str, start: date, end: date, point: float) -> Path:
    """Write one CSV for the whole range from the cached daily archives."""
    csv_path = side_dir / "m1.csv"
    written = 0
    with csv_path.open("w", encoding="utf-8") as handle:
        handle.write("timestamp,open,high,low,close,volume\n")
        day = start
        while day < end:
            path = side_dir / "days" / f"{day.isoformat()}.bi5"
            if path.exists() and path.stat().st_size:
                handle.write(csv_rows(day, decode_records(path.read_bytes()), point))
                written += 1
            day += timedelta(days=1)
    print(f"{symbol.upper()} {side}: {written} day files -> {csv_path}")
    return csv_path


def run(
    symbol: str,
    start: date,
    end: date,
    sides: tuple[str, ...],
    root: Path,
    workers: int,
    point: float,
) -> None:
    """Download every day for the given sides and write the merged CSVs."""
    days = [start + timedelta(days=offset) for offset in range((end - start).days)]
    for side in sides:
        side_dir = root / f"{symbol.lower()}-{side.lower()}"
        counts = {"ok": 0, "cached": 0, "missing": 0, "failed": 0}
        missing: list[str] = []
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    download_day, symbol, day, side, side_dir / "days" / f"{day.isoformat()}.bi5"
                ): day
                for day in days
            }
            for done, future in enumerate(as_completed(futures), start=1):
                day, result = futures[future], future.result()
                counts[result] += 1
                if result == "missing":
                    missing.append(day.isoformat())
                if done % 100 == 0 or done == len(days):
                    rate = done / max(time.monotonic() - started, 1e-9)
                    print(f"{symbol.upper()} {side}: {done}/{len(days)} ({rate:.1f}/s) {counts}")
        side_dir.mkdir(parents=True, exist_ok=True)
        (side_dir / "missing.txt").write_text("\n".join(missing) + ("\n" if missing else ""))
        merge(side_dir, symbol, side, start, end, point)


def selftest() -> None:
    """Known-answer check of the archive decoder; run with ``--selftest``."""
    live = struct.pack(">IIIIIf", 60, 104_228, 104_231, 104_226, 104_252, 5.0)
    flat = struct.pack(">IIIIIf", 120, 104_231, 104_231, 104_231, 104_231, 0.0)
    records = decode_records(lzma.compress(live + flat, format=lzma.FORMAT_ALONE))
    assert records[0][-1] == 5.0 and records[1][-1] == 0.0
    body = csv_rows(date(2022, 11, 1), records, 1e-5)
    assert body == "1667260860000,1.042280,1.042520,1.042260,1.042310,5.0\n", body
    assert archive_url("eurusd", date(2022, 11, 1), "bid").endswith(
        "/EURUSD/2022/10/01/BID_candles_min_1.bi5?v=edgebench"
    )
    print("selftest ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Dukascopy daily M1 candle archives")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2022, 11, 1))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2026, 11, 1))
    parser.add_argument("--side", choices=("both", "bid", "ask"), default="both")
    parser.add_argument("--dir", type=Path, default=Path("data/raw/dukascopy"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--point", type=float, default=1e-5, help="price unit (EURUSD 1e-5)")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        selftest()
        return 0
    if args.start >= args.end:
        print("--from must be before --to", file=sys.stderr)
        return 2
    sides = SIDES if args.side == "both" else (args.side.upper(),)
    run(args.symbol, args.start, args.end, sides, args.dir, args.workers, args.point)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
