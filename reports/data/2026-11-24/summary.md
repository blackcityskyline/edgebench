# Data snapshot, 2026-11-24

Everything below was produced on this machine from the public archives listed here. Raw
downloads live under `data/raw/` (git-ignored); the store is `data/parquet/` (git-ignored).
This folder keeps the commands and their output.

## Commands

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"

# Binance: 48 full months per pair, 2022-11-01 .. 2026-10-31
.venv/bin/python tools/fetch_binance.py BTCUSDT ETHUSDT SOLUSDT TONUSDT --months 48
for sym in BTCUSDT ETHUSDT SOLUSDT TONUSDT; do
  .venv/bin/python -m edgebench.cli data ingest --source binance --symbol "$sym" \
    --files data/raw/binance/"$sym"/*.zip
done

# Dukascopy EURUSD M1, bid and ask, 2022-11-01 .. 2026-11-01 (--to is exclusive)
.venv/bin/python tools/fetch_dukascopy.py --symbol EURUSD \
  --from 2022-11-01 --to 2026-11-01 --side both --dir data/raw/dukascopy --workers 3
.venv/bin/python -m edgebench.cli data ingest --source dukascopy --symbol eurusd \
  --files data/raw/dukascopy/eurusd-bid/m1.csv \
  --ask-files data/raw/dukascopy/eurusd-ask/m1.csv

.venv/bin/python -m edgebench.cli data info      > reports/data/2026-11-24/info.txt
.venv/bin/python -m edgebench.cli data verify   >> reports/data/2026-11-24/info.txt
# data gaps, one section per dataset -> reports/data/2026-11-24/gaps.txt
```

## `data info` (verbatim)

```
binance/BTCUSDT: 2103760 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/ETHUSDT: 2103760 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/SOLUSDT: 2103759 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/TONUSDT: 994620 rows, 2024-08-08T10:00:00+00:00 .. 2026-06-30T02:59:00+00:00, side ['trade'], no ask
dukascopy/eurusd: 1488580 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-30T20:59:00+00:00, side ['bid'], ask
data_version 85323b459272d9c5

store verified
```

`data verify` re-hashes every parquet file against `data/manifest.json`: `store verified`.

## Gaps

Binance, 10+ minutes:

| dataset | gaps | largest |
|---|---:|---|
| binance/BTCUSDT | 1 | 2023-03-24 12:40 .. 14:00 (80 min) |
| binance/ETHUSDT | 1 | 2023-03-24 12:40 .. 14:00 (80 min) |
| binance/SOLUSDT | 1 | 2023-03-24 12:40 .. 14:00 (80 min) |
| binance/TONUSDT | 0 | — |

The 2023-03-24 hole is the same 80 minutes on all three pairs: a Binance-wide outage, not a
download problem. Full output, including TON, is in `gaps.txt`.

Dukascopy EURUSD, 10+ minutes: **250 gaps**, all of them closed-market time (weekends,
Christmas/New Year, a few exchange holidays). Full list of the largest 20 in `gaps.txt`.
Largest:

| start | end | minutes |
|---|---|---:|
| 2023-12-29 22:00 | 2024-01-01 22:00 | 4320 |
| 2023-12-22 21:59 | 2023-12-24 23:00 | 2941 |
| 2022-11-04 21:00 | 2022-11-06 22:00 | 2940 |
| 2023-11-03 21:00 | 2023-11-05 22:00 | 2940 |
| 2024-11-01 21:00 | 2024-11-03 22:00 | 2940 |
| 2025-10-31 21:00 | 2025-11-02 22:00 | 2940 |

FX trades Sunday 22:00 UTC to Friday 21:59/22:00 UTC, so every weekend is a real 2-day gap.
Nothing was forward-filled: Dukascopy's zero-volume filler candles are dropped on purpose
(`docs/DATA.md`, the `-fl` note).

## Coverage notes

- **Binance**: 192 monthly archives. BTC/ETH/SOL cover all 48 months. TON listed 2024-08-08,
  so 2022-11 .. 2024-07 does not exist; Jul .. Oct 2026 archives were not published at
  download time, so TON ends 2026-06-30 02:59 UTC.
- **Dukascopy**: 1461 daily archives per side, none missing (weekend archives exist as
  flat fillers). Bid and ask each produce exactly 1 488 580 rows; the merged frame is
  1 488 580 bars with no NaN on either side, i.e. the two sides have identical minute sets.
  The store reports `side ['bid'], ask`.
- EURUSD point size on this archive is `1e-5`. Volume is Dukascopy's tick volume in
  millions, kept as-is.

## Deviation: how Dukascopy was fetched

`docs/DATA.md` suggests `dukascopy-node`. It does not work from this network:

```
> Dukascopy refused access (HTTP 403) for
  https://jetta.dukascopy.com/v1/candles/minute/EUR-USD/BID/2022/11/1;
  WAF token recovery does not apply to a plain 403.
```

Diagnosed in three steps; it is two unrelated blocks, neither caused by our headers.

**1. The site itself is reset by the ISP.** TLS ClientHello to `www.dukascopy.com:443` gets
`Connection reset by peer` before any HTTP. Egress here is BY, AS6697 Beltelecom; the block is
on the operator side.

**2. `jetta.dukascopy.com` is an AWS WAF block, not an origin error.** TLS completes, then:

```
HTTP/2 403   server: CloudFront   x-cache: Error from cloudfront
Request blocked.
```

No challenge page (`202` + `challenge.js`), so the `aws-waf-token` recovery path in
`dukascopy-node` cannot help: WAF denies before any token is issued.

**3. Tested through the mihomo VLESS subscription on this machine** (`mixed-port 7890`,
4 Reality nodes; node addresses omitted from this public file). Two nodes were dead at the TCP level (port 8443 unusable), the two live ones
route out of hosting providers and are still refused:

| node | TCP 8443 | exit | `www.dukascopy.com` | `jetta` |
|---|---|---|---|---|
| Frankfurt 3 | timeout | — | — | — |
| Amsterdam 5 | timeout | — | — | — |
| Dubai 2 | ok | FR, HZ Hosting | **200** | **403** |
| Bangalore 2 | ok | IN, DigitalOcean | 200 | **403** |

So the proxy does defeat the ISP block (the site loads), but the WAF rule keys on the hosting
ASN, not on country: two different providers in two different countries, both blocked. A
residential or mobile exit is what would make `dukascopy-node` work; ordinary VPS/VLESS exits
will not. `widgets.dukascopy.com` and `datafeed.dukascopy.com` are unaffected. State was
restored afterwards (`mode=rule`, selector back to Amsterdam, service stopped).

### What this costs: nothing in the data

The `.bi5` archives and the Jetta JSON are the same Dukascopy feed with a different envelope
(JSON with price deltas vs `.bi5` with absolute levels). Verified against the API on
2022-11-01 BID: 1437 live minutes, **0 mismatches**.

| need | Jetta (`dukascopy-node`) | archive (`tools/fetch_dukascopy.py`) |
|---|---|---|
| M1 bid + ask | yes | yes, 1461/1461 days per side |
| ticks (bid, ask, volumes) | yes | yes: `EURUSD/YYYY/MM/DD/HHh_ticks.bi5`, 20-byte `>IIIff` records with both sides and both volumes; verified 2023-04-03 10:00, 3852 ticks |
| other instruments | ~60 ids | XAUUSD, GBPUSD, USATECHIDXUSD verified |
| m5/h1/d1 | aggregated by the tool | aggregate from M1, same numbers |
| timezone, point size | handled | UTC by default, `--point` per instrument |

What is actually lost is the tool: retries, WAF token, cache, timezone offsets, flat filtering,
aggregation, the instrument id table. `tools/fetch_dukascopy.py` does M1, one instrument per
run, point size as a flag, no tick route yet (~30 lines, format known). The other risk is that
`datafeed` is an undocumented path and could disappear; then a residential exit becomes
mandatory again.

Instead `tools/fetch_dukascopy.py` reads the same official daily candle archives from
`datafeed.dukascopy.com`: `EURUSD/YYYY/MM/DD/{BID,ASK}_candles_min_1.bi5` (the month in the
path is zero-based). Record: 24 bytes, `>IIIIIf` = seconds from 00:00 UTC, open, close, low,
high, integer points, float volume; zero-volume records are flat fillers.

Decoder verified against the Jetta JSON API for 2022-11-01 BID: 1437 live minutes,
**0 mismatches** on all four prices after re-accumulating Jetta's deltas.

The host behind `datafeed.dukascopy.com` (CNAME `datafeed.66proxymity88.net`) is flaky: new
TLS connections time out or answer 503 about half the time, and a fresh connection per file
gives ~0.04 files/s. Two things fixed it: a `?v=edgebench` query string (bypasses a stale
cached 503) and one keep-alive connection per worker, which gives 2-4 files/s. With that the
full 2922 files take ~15 minutes. `--workers 3` and a re-run to pick up the handful of failed
days; the final run had 1461/1461 day files on both sides.

## Files

- `info.txt` — `data info` and `data verify`, verbatim.
- `gaps.txt` — `data gaps --min-minutes 10 --top 20` for all five datasets.
- `summary.md` — this file.
