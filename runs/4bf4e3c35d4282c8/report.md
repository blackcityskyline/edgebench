# Run 4bf4e3c35d4282c8: strategy_v1 on dev

config `acf8cb35b049` | data `85323b459272` | code `7d21e9e-dirty` | cost x1 | trials so far: 1

**Warnings**
- EURUSD: placeholder costs
- instrument BTCUSDT: placeholder costs
- instrument ETHUSDT: placeholder costs
- instrument EURUSD: placeholder costs
- instrument GBPUSD: placeholder costs
- instrument SOLUSDT: placeholder costs
- instrument TONUSDT: placeholder costs
- instrument US100: placeholder costs
- instrument XAUUSD: placeholder costs
- session crypto_evening: window not confirmed by the owner
- session london: window not confirmed by the owner
- session ny_am: window not confirmed by the owner
- smoke test: only the last 30 days of each dataset

## Funnel

| instrument | m1_bars | zones_fvg | zones_fractal | events | candidates | trades_opened |
|---|---|---|---|---|---|---|
| EURUSD | 28899 | 49 | 116 | 141 | 6 | 6 |

Skipped: skip_session=413, skip_stop_too_tight=315, skip_stop_too_wide=2

Cells show `E[R] [95% day-block interval]`; `*` means the interval excludes zero. Groups with n<30 are not evaluated. Many cells are shown, so some `*` are expected by chance (no multiple-comparison correction).

## By trigger (all instruments)

| trigger | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| inside | 1 | 1 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| rejection | 2 | 2 | 50% | n<30 | 50% | n<30 | 50% | n<30 | 50% | n<30 | 0% | n<30 |
| sweep | 3 | 3 | 67% | n<30 | 67% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |

## By instrument

| instrument | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD | 6 | 5 | 50% | n<30 | 50% | n<30 | 17% | n<30 | 17% | n<30 | 0% | n<30 |

## By side

| side | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LONG | 3 | 2 | 33% | n<30 | 33% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| SHORT | 3 | 3 | 67% | n<30 | 67% | n<30 | 33% | n<30 | 33% | n<30 | 0% | n<30 |

## By session

| session | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| london | 4 | 3 | 25% | n<30 | 25% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| ny_am | 2 | 2 | 100% | n<30 | 100% | n<30 | 50% | n<30 | 50% | n<30 | 0% | n<30 |

## By zone kind

| zone_kind | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| FRACTAL | 1 | 1 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| FVG | 5 | 4 | 60% | n<30 | 60% | n<30 | 20% | n<30 | 20% | n<30 | 0% | n<30 |

## By exit of the reference policy

| exit_reason | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| STOP | 3 | 2 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| TARGET | 3 | 3 | 100% | n<30 | 100% | n<30 | 33% | n<30 | 33% | n<30 | 0% | n<30 |

## Instrument x trigger

| cell | n | days | hit 1R | E[R] @1R | hit 2R | E[R] @2R | hit 3R | E[R] @3R | hit 5R | E[R] @5R | hit 10R | E[R] @10R |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EURUSD / inside | 1 | 1 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |
| EURUSD / rejection | 2 | 2 | 50% | n<30 | 50% | n<30 | 50% | n<30 | 50% | n<30 | 0% | n<30 |
| EURUSD / sweep | 3 | 3 | 67% | n<30 | 67% | n<30 | 0% | n<30 | 0% | n<30 | 0% | n<30 |

Ambiguous bars (stop and target in one bar, stop wins): 0 in 6 trades.
