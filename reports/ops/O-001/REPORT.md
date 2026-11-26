# O-001 first real-data run: done

updated 2026-11-26T10:38:46+00:00

| step | status | seconds |
|---|---|---|
| gates | ok | 17.6 |
| data_info | ok | 1.3 |
| data_verify | ok | 8.6 |
| split | ok | 1.7 |
| split_freeze | ok | 2.0 |
| config_check | ok | 2.0 |
| spreads | ok | 2.8 |
| smoke | ok | 5.7 |
| full | ok | 1060.8 |
| cost2 | ok | 1158.7 |
| charts | ok | 9.1 |
| charts_blind | ok | 8.6 |

## gates

```
PASS  G1 lint and format
SKIP  G2  (not part of --quick)
PASS  G3 unit tests
SKIP  G4  (not part of --quick)
SKIP  G5  (not part of --quick)
PASS  G6 config schema  (1 strategy file(s))
SKIP  G7 protected paths  (not a worker branch (agent/*))
PASS  G8 repo hygiene
gates: ok (SKIP is not PASS)
```

## data_info

```
binance/BTCUSDT: 2103760 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/ETHUSDT: 2103760 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/SOLUSDT: 2103759 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-31T23:59:00+00:00, side ['trade'], no ask
binance/TONUSDT: 994620 rows, 2024-08-08T10:00:00+00:00 .. 2026-06-30T02:59:00+00:00, side ['trade'], no ask
dukascopy/eurusd: 1488580 rows, 2022-11-01T00:00:00+00:00 .. 2026-10-30T20:59:00+00:00, side ['bid'], ask
data_version 85323b459272d9c5
```

## data_verify

```
store verified
```

## split

```
horizon  2022-11-01 00:00:00+00:00 .. 2026-11-01 00:00:00+00:00
dev      2022-11-01 .. 2026-01-10 (exclusive)
embargo  2 days
holdout  from 2026-01-12 (derived)
```

## split_freeze

```
horizon  2022-11-01 00:00:00+00:00 .. 2026-11-01 00:00:00+00:00
dev      2022-11-01 .. 2026-01-10 (exclusive)
embargo  2 days
holdout  from 2026-01-12 (derived)
written <repo>/config/splits.yaml; commit it so the boundary stays fixed
```

## config_check

```
strategy_v1: ok, hash acf8cb35b049
warning: instrument EURUSD: placeholder costs
warning: instrument GBPUSD: placeholder costs
warning: instrument XAUUSD: placeholder costs
warning: instrument US100: placeholder costs
warning: instrument BTCUSDT: placeholder costs
warning: instrument ETHUSDT: placeholder costs
warning: instrument SOLUSDT: placeholder costs
warning: instrument TONUSDT: placeholder costs
warning: session london: window not confirmed by the owner
warning: session ny_am: window not confirmed by the owner
warning: session crypto_evening: window not confirmed by the owner
```

## spreads

```
dukascopy/eurusd: n=1488580 median=3e-05 p25=2e-05 p75=5e-05 p95=9e-05
  median by UTC hour: 00:3e-05 01:3e-05 02:3e-05 03:3e-05 04:3e-05 05:3e-05 06:3e-05 07:3e-05 08:3e-05 09:3e-05 10:3e-05 11:3e-05 12:3e-05 13:3e-05 14:3e-05 15:3e-05 16:3e-05 17:3e-05 18:3e-05 19:3e-05 20:3e-05 21:0.00014 22:7e-05 23:4e-05
```

## smoke run (console)

```
EURUSD: loading dukascopy/eurusd (dev)
  events 141, candidates 6, trades 6
report: <repo>/runs/4bf4e3c35d4282c8/report.md
tables: <repo>/data/runs/4bf4e3c35d4282c8
```

## full run (console)

```
EURUSD: loading dukascopy/eurusd (dev)
  events 6435, candidates 817, trades 814
BTCUSDT: loading binance/BTCUSDT (dev)
  events 9718, candidates 6704, trades 6704
ETHUSDT: loading binance/ETHUSDT (dev)
  events 9836, candidates 7195, trades 7195
SOLUSDT: loading binance/SOLUSDT (dev)
  events 9321, candidates 5860, trades 5860
TONUSDT: loading binance/TONUSDT (dev)
  events 4082, candidates 1564, trades 1564
report: <repo>/runs/2e6a0a6209d121f2/report.md
tables: <repo>/data/runs/2e6a0a6209d121f2
```

Full report: `reports/ops/O-001/run-full.md` (also `runs/2e6a0a6209d121f2/report.md`).

## cost x2 run (console)

```
EURUSD: loading dukascopy/eurusd (dev)
  events 6435, candidates 52, trades 52
BTCUSDT: loading binance/BTCUSDT (dev)
  events 9718, candidates 6685, trades 6685
ETHUSDT: loading binance/ETHUSDT (dev)
  events 9836, candidates 7161, trades 7161
SOLUSDT: loading binance/SOLUSDT (dev)
  events 9321, candidates 4649, trades 4649
TONUSDT: loading binance/TONUSDT (dev)
  events 4082, candidates 568, trades 568
report: <repo>/runs/3b82c28e0c72b068/report.md
tables: <repo>/data/runs/3b82c28e0c72b068
```

Full report: `reports/ops/O-001/run-cost2.md` (also `runs/3b82c28e0c72b068/report.md`).

Full console log: `reports/ops/O-001/log.txt`.
