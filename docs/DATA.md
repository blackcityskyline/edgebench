# Getting and using price data

Prices stay on your disk (`data/`, git-ignored). The repository holds code, configs, reports and labels only. Run the download steps on your own machine; the cloud workspace used by the architect cannot reach these hosts.

## 1. Binance (BTC, ETH, SOL, TON against USDT)

```
python tools/fetch_binance.py BTCUSDT ETHUSDT SOLUSDT TONUSDT --months 48
edgebench data ingest --source binance --symbol BTCUSDT --files data/raw/binance/BTCUSDT/*.zip
```

Files come from `data.binance.vision` (monthly spot klines, 1m) and are checked against the published `.CHECKSUM`. The script skips files that are already verified, so re-running resumes. TONUSDT starts when Binance listed it; earlier months are reported as not available. Binance has no kline for a minute without trades, so thin markets have real gaps. Timestamps are milliseconds in older files and microseconds from 2025; the parser detects the unit and refuses values that decode outside 2005-2100.

Price side is `trade` (last trade price), not bid or ask.

## 2. Dukascopy (EURUSD, GBPUSD, XAUUSD, US100)

Dukascopy candles are single-sided, so download bid and ask separately and merge them while ingesting. With `dukascopy-node` (flags checked against its CLI documentation):

```
npx dukascopy-node -i eurusd -from 2023-01-01 -to 2025-11-01 -t m1 -p bid -f csv -dir data/raw/dukascopy/eurusd-bid
npx dukascopy-node -i eurusd -from 2023-01-01 -to 2025-11-01 -t m1 -p ask -f csv -dir data/raw/dukascopy/eurusd-ask
edgebench data ingest --source dukascopy --symbol eurusd \
  --files data/raw/dukascopy/eurusd-bid/*.csv --ask-files data/raw/dukascopy/eurusd-ask/*.csv
```

Notes:
- Do not pass `-fl` (flats). Flat candles are zero-volume fillers for weekends and holidays; the store keeps real gaps instead.
- The output timestamp is UTC. The parser accepts an epoch (`timestamp` column) or ISO strings (`time`, `datetime`, `date`). If your version names the column differently, `ingest` fails with the list of columns it found.
- Instrument ids confirmed by a real download (2026-11-24 snapshot): `eurusd`, `gbpusd`, `xauusd`, and the Nasdaq-100 index `usatechidxusd` (shown on the site as USATECH.IDX/USD). If you pull a different symbol name than the one in `instruments.yaml`, use that name in `--symbol`.
- The index is a CFD, not the NQ future (decision D9).

### If `dukascopy-node` is blocked (HTTP 403)

The `jetta.dukascopy.com` endpoint used by `dukascopy-node` is behind a WAF that refuses many hosting and some national networks. `tools/fetch_dukascopy.py` reads the same daily candle archives from `datafeed.dukascopy.com` instead (see `reports/data/2026-11-24/summary.md` for the diagnosis and the check against the JSON API: 0 mismatches):

```
python tools/fetch_dukascopy.py --symbol EURUSD --from 2022-11-01 --to 2026-11-01 --side both --dir data/raw/dukascopy --workers 3
edgebench data ingest --source dukascopy --symbol eurusd \
  --files data/raw/dukascopy/eurusd-bid/m1.csv --ask-files data/raw/dukascopy/eurusd-ask/m1.csv
```

Prices in these archives are integers scaled by a per-instrument point size (`--point`, default 1e-5 for EURUSD). Before trusting a new instrument, compare a few ingested prices with a chart (gold and the index use a different scale than a 5-digit forex pair). `datafeed` is an undocumented path and may change; keep the downloaded raw files.

Ask candles let the engine use a real spread. Without them the fixed placeholder spread from `config/instruments.yaml` applies, which is optimistic around news and at rollover.

## 3. Inspect and verify

```
edgebench data info                 # datasets, ranges, price side, ask availability, data_version
edgebench data verify               # recompute hashes against data/manifest.json
edgebench data gaps --source binance --symbol BTCUSDT --min-minutes 10
```

Check the gap list before trusting a dataset: weekends and holidays are expected for forex and indices; long gaps in crypto usually mean a missing file.

## 4. Freeze the dev/holdout boundary (once)

```
edgebench data split          # show what would be derived
edgebench data split --write  # freeze it into config/splits.yaml, then commit that file
```

The last 20% of the common horizon becomes holdout, with an embargo of 2 days before it. The boundary is derived once and written down; it never moves when more data is added, because a moving boundary would silently turn data you have already looked at into holdout. After freezing, research code reaches prices only through `edgebench.data.load_m1`/`load_bars`; asking for `holdout` needs `EDGEBENCH_HOLDOUT_TOKEN` in your shell, a stated reason, and writes a line to `holdout/ledger.jsonl`.

## 5. Where data lives

```
data/raw/            downloads (zips, csv)         not tracked
data/parquet/        <source>/<symbol>/m1/<year>.parquet   not tracked
data/manifest.json   per-file rows, range, price side, hashes
```

`data_version` hashes the content fields of the manifest (not file bytes), so a pyarrow upgrade does not change it. Re-ingesting the same files changes nothing; a file that disagrees with a stored minute is refused instead of overwriting it. Set `EDGEBENCH_DATA` to keep the store somewhere else.

## 6. Limits worth knowing

- M3 and H1 are derived from M1 (`edgebench.data.resample`). A bar built from less than 80% of its minutes is marked incomplete and never used to build zones (placeholder threshold).
- Binance minute data comes from trades, so the high and low of a thin minute can sit far from a tradable quote. Treat micro-stop results on small crypto pairs with extra suspicion until costs are measured.
- Nothing here removes survivorship or listing-date effects: TONUSDT history starts at its listing.
