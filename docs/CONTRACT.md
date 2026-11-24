# edgebench contract v0.1 (DRAFT)

Status: draft for owner review. Items marked **[DECISION Dn]** are open choices with a default; the default is used until the owner decides otherwise. Parameter values in examples are placeholders, not recommendations. Changing this file is an architect-role action (see section 9).

## 0. Scope

In scope: historical research of a discretionary price-action strategy.
H1 context zones (fair value gaps, fractal levels) -> M1-M3 behavior at the zone (sweep, stall, rejection wick, inside-bar-like stall) -> micro-stop entry -> results in R-multiples. Plus an automated development and experiment loop around it.

Out of scope for v0: live trading, order routing, broker APIs, any autonomous decision on real money.

## 1. Principles

- **P1 Causality by construction.** A streaming engine (4.6) is the source of truth. Strategy components receive bars only through `on_bar`, so they cannot see the future. A causality test is a backstop, not the main defense.
- **P2 Compute is code, AI is optional.** Detection, execution and statistics are deterministic code. AI (evaluator, research suggestions) sits on top and is replaceable. Nothing requires a particular model.
- **P3 Every derived object has `formed_at` and `known_at`.** Nothing is used before `known_at`.
- **P4 Results are distributions in R, net of costs, with intervals and baselines.** Never a single equity curve or a bare win rate.
- **P5 Reproducible.** `run_id = hash(config, data_version, code_commit)`. Same inputs give byte-identical outputs.
- **P6 Pessimism on ambiguity.** When OHLC cannot tell what happened first, assume the worse outcome.
- **P7 Dev data is for building, holdout is touched only through a guarded command.**
- **P8 Small modules, typed contracts, tests with known answers, gates that workers cannot edit.**

## 2. Conventions

### 2.1 Time

- All timestamps are UTC, timezone-aware, nanosecond precision.
- A bar is identified by `ts_open` and becomes *available* at `ts_close = ts_open + tf`.
- **Information rule:** a decision at time `T` may use only bars with `ts_close <= T` and objects with `known_at <= T`.
- Decisions are made at M1 bar close (`T` = `ts_close` of that bar). An order created at `T` may fill only on bars with `ts_open >= T`. No same-bar fills.
- **Ordering at the same timestamp `T`:** (1) M1 bar closes, (2) M3/H1 bars ending at `T` are completed, (3) zone detectors run, (4) the strategy decides. A zone that becomes known at `T` cannot be touched by the bar that closed at `T`.
- Forming (incomplete) M3/H1 bars are never visible. **[DECISION D8]** default: closed bars only.
- Sessions are windows in a named IANA timezone (default `America/New_York`) so DST is handled. They live in `config/sessions.yaml`; one function `session_of(ts)` labels timestamps. **[DECISION D3]** the owner supplies the windows (London, NY AM, crypto evening).

### 2.2 Prices, sides and R

- Prices are float64. Bar prices are **bid** unless the manifest says `price_side: ask|mid`.
- Spread `s` = ask - bid at that time (a series when ask candles exist, otherwise the spread model from `config/instruments.yaml`).
- Side-aware fills, implemented in exactly one module (`execution/fills.py`) and covered by a table-driven test:

| action | fill price | triggered when (bid bar) |
|---|---|---|
| long entry, market | ask = bid + s | n/a |
| long stop (sell) | stop price, minus slippage | bid low <= stop |
| long target (limit sell) | target price | bid high >= target |
| short entry, market | bid | n/a |
| short stop (buy) | stop price, plus slippage | bid high + s >= stop |
| short target (limit buy) | target price | bid low + s <= target |

- `risk_distance = |entry_fill - stop_price|`. `r_net = (exit_fill - entry_fill) * direction / risk_distance - commission_in_R`. Spread is already inside the fills, so it is not subtracted twice.
- ATR units: `atr_m1` and `atr_h1` are Wilder ATR(14) on completed M1 and H1 bars, computed only from bars available at `T`.

### 2.3 Intra-bar ambiguity

If one bar can both stop out and reach a target (or fill and stop), the stop wins. Evaluation of a trade starts with the entry bar itself. The number of such bars is stored as `ambiguous_bars`. The engine exposes a `resolver` hook so a later pass can resolve ambiguous bars with tick data; the default resolver is pessimistic.

### 2.4 Identifiers

Deterministic: `zone_id = {instrument}:{kind}:{dir}:{formed_at_iso}`, `event_id = {zone_id}#{episode_index}`, `candidate_id = {event_id}:{trigger}`. A candidate is a possible trade created by one trigger; if it is executed, its `trade_id` equals its `candidate_id`.

## 3. Data layer

- **Base resolution is M1**, stored as parquet per instrument and year: `data/parquet/{source}/{symbol}/m1/{year}.parquet` with `ts_open, open, high, low, close, volume`, plus `ask_open..ask_close` for forex when ask candles are downloaded.
- M3 and H1 are derived by one function `resample(m1, tf)`: label = open time, left-closed, with a completeness flag. A derived bar built from fewer than `min_m1_fraction` of the expected M1 bars is `incomplete`, and zones are never built from incomplete bars. Gaps are never filled with synthetic bars.
- `data/manifest.json` records per file: sha256 of the file bytes, `content_sha256` of the canonical frame contents, row count, first and last timestamp, source, `price_side`, loader version. `data_version` is the sha256 of the manifest's *content* fields only (file-byte hashes excluded, so upgrading pyarrow does not change it), optionally limited to the datasets a run uses. Two stricter rules: re-ingesting identical minutes changes nothing, and a minute that differs from the stored one is refused, never overwritten. Valid `price_side` values: `bid`, `ask`, `mid`, `trade` (Binance last-trade prices).
- Sources (v0): Dukascopy for EURUSD, GBPUSD, XAUUSD and the Nasdaq-100 index CFD (bid and, ideally, ask candles); Binance public archives for BTC, ETH, SOL and TON against USDT. **[DECISION D9]** US100 CFD is the default; NQ futures data is paid and can be added later.
- Loader pitfalls that need tests: Binance timestamps can be milliseconds or microseconds depending on the file date (detect by magnitude); Dukascopy times are UTC; weekends and holidays are gaps; duplicate rows occur.
- **Size and horizon.** M1 OHLC for one instrument-year is tens of MB, so the 50 GB budget only matters for ticks. **[DECISION D7]** default horizon: as many years as the sources give, up to 4, at least 12 months. More history is the cheapest way to get statistical power for a heavy-tailed strategy.
- `/data/` (repository root only) is git-ignored. `edgebench.data.synthetic` (in the package, so tests, gates and later modules can import it) generates seeded random-walk M1 bars and builds hand-made OHLC sequences for fixtures, so CI and gates never need real data. Real downloads and their commands are described in `docs/DATA.md`.
- Splits (7.1) are applied by the loader, which returns `split=dev` by default.

## 4. Domain objects and modules

### 4.1 Objects

Package `edgebench.contracts`, frozen dataclasses. Changes require the architect.

- **Bar**: `ts_open, open, high, low, close, volume, tf, complete`
- **Zone**: `zone_id, instrument, kind (FVG|FRACTAL), direction (BULL|BEAR), low, high, extreme_ts, formed_at, known_at, params_hash`. BULL = support, long bias. For FRACTAL, `low == high` is the level.
- **ZoneEvent**: `zone_id, ts, type (CREATED|TOUCH_START|TOUCH_END|MITIGATED|INVALIDATED|EXPIRED), episode_index`. `ts` is the close of the M1 bar that caused the event. `episode_index` is set on touch events (0 = first episode of the zone).
- **Observation**: `detector, ts_decision, direction, refs, metrics` (for example sweep depth in ATR)
- **Event** (one row per touch episode): `event_id, zone_id, instrument, direction, touch_start, session, features, observations`. Features include zone age, zone size in `atr_h1`, distance to the nearest opposite liquidity. An episode can contain several decision times, so the decision time lives on the candidate, not the event.
- **OrderIntent** (a candidate trade, the unit for the evaluator and for labels): `candidate_id, event_id, trigger, ts_decision, direction, entry_policy, entry_ref, stop_price`
- **Trade**: `trade_id, entry_ts, entry_fill, stop_price, risk_distance, exit_ts, exit_reason, exit_fill, r_net, mfe_r, mae_r, ambiguous_bars, cost_r, ladder`
- **RunManifest**: `run_id, config_hash, data_version, code_commit, split, started, finished, counts`

### 4.2 Configuration

Strategy rules live in `config/strategy_*.yaml`, validated by pydantic (`edgebench.config`). Every parameter has a default and a docstring. Sketch in section 6.

### 4.3 Zones (`edgebench.zones`)

Streaming interface: `ZoneDetector.on_bar(h1_bar) -> list[Zone]`, stateful, closed H1 bars only.

- **FVG.** Three consecutive complete H1 bars `c1, c2, c3`. Bull: `low(c3) > high(c1)`, zone `[high(c1), low(c3)]`. Bear: `high(c3) < low(c1)`, zone `[high(c3), low(c1)]`. `formed_at = known_at = ts_close(c3)`. Filters: `min_size_atr_h1`, optional `min_displacement_body_atr_h1` on `c2`.
- **No pattern across a hole.** A zone detector's window holds only consecutive complete bars (`BarWindow`). A time gap (weekend, outage) or an incomplete bar empties it, so a gap or fractal is never formed across missing data. Zones are not emitted while the ATR is still warming up (14 H1 bars), because the size filter cannot be evaluated.
- **Fractal level.** Pivot high/low with `left` bars on the left and `right` bars on the right. **[DECISION D1]** default 2/2 (Williams); 1/1 is the 3-bar swing. `extreme_ts` is the open of the pivot bar, `formed_at` is the close of the pivot bar, and **`known_at` is the close of the `right`-th bar after the pivot.** Using the level before `known_at` is look-ahead and the most common bug in this kind of backtest. BULL fractal = pivot low (liquidity below), BEAR fractal = pivot high.
- **ZoneBook.** `ZoneBook.on_m1(bar) -> list[ZoneEvent]` tracks the lifecycle. A *touch* is an M1 bar with `ts_open >= known_at` whose range overlaps the zone (fractal: range reaches the level). A touch *episode* starts at the first such bar and ends after `episode_gap_bars` consecutive M1 bars outside the zone.
  Events are stamped with the close of the M1 bar. When a zone is retired during an active episode, `TOUCH_END` is emitted first. Expiry is measured from `known_at` to the bar close. After `max_episodes` finished episodes the zone is `MITIGATED`.
- **[DECISION D2]** invalidation: `invalid_on in {close_through, full_fill, first_touch, never}`, default `close_through`. Checked on every M1 bar, also without a touch. For a BULL zone (BEAR mirrored): `close_through` = an M1 close below the zone low (a wick through the zone that closes back inside is a sweep, not an invalidation); `full_fill` = a bar low reaches the zone low; `first_touch` = the zone is spent as soon as its first episode ends; `never` = no invalidation. `max_episodes` default 1, `max_age_h1_bars` default 200. FVG and fractal have separate settings of the same shape (`zones.fvg.*`, `zones.fractal.*`).

### 4.4 Patterns (`edgebench.patterns`)

Each detector: `on_bar(bar, ctx) -> list[Observation]`. It runs only while an episode is active (from touch start until `window_bars` later). Observations are non-exclusive: one bar can fire several detectors. An observation is available at the close of the bar that completes it.

- **Sweep.** Price trades beyond a reference level, then a bar closes back inside within `max_return_bars`. Reference set is configurable: `zone_edge`, `h1_fractal`, `ltf_fractal_m1`, `ltf_fractal_m3`. LTF fractals obey the same `known_at` rule. Params: `min_depth_atr_m1`, `max_return_bars`.
- **Stall.** `n_bars` consecutive bars with `range <= max_range_atr_m1` and no new extreme beyond `max_extension_atr_m1`.
- **Rejection wick.** Wick/range >= `min_wick_ratio` on the side facing the zone's reaction direction, close within the far `close_zone` fraction of the range.
- **Inside-like.** Bar range (or body) inside the previous bar's range (or body), per `mode`, optionally requiring `min_count` bars.

Fixtures: `tests/fixtures/patterns/*.json`, hand-built bar sequences with expected observations. The owner's real examples are added here later.

### 4.5 Strategy and execution

- `Strategy.on_m1(bar, ctx) -> list[OrderIntent]` is a pure function of config and context.
- **[DECISION D5]** entry policy: `market_next_open` (default), `limit_retrace(frac)`, `stop_break`.
- Stop: beyond the structure extreme that produced the trigger (sweep extreme or rejection-bar extreme), plus `stop_buffer` (in spreads and/or ATR).
- Filters: `min_stop_spreads`, `max_stop_atr_h1`, sessions, optional news blackout from a calendar CSV, one open position per instrument. **[DECISION D6]** `max_trades_per_zone` default 1. `combine: first | all_of` decides how several triggers combine.
- `Broker` turns intents into fills with the rules of 2.2 and the cost model in `config/instruments.yaml` (tick size, spread model = series or fixed per session, slippage model, commission). It never looks beyond the current bar.
- **Exits are separate from entries. [DECISION D4]** For every trade the engine records a first-passage ladder: time to stop and time to each of `ladder_r` (default +1, 2, 3, 5, 8, 10, 15 R) within `max_hold_minutes`, plus `r_at_timeout`. Fixed-R policies are computed from the ladder. Path-dependent policies (liquidity target, partials, trailing) are `ExitPolicy` classes replayed on stored paths. This separates "is there edge in the entry" from "which exit captures it".
- **Two simulation modes.** `shadow` (default for research): every trigger that fires creates its own candidate and its trade is simulated independently, with no position limit and no `combine` rule. This is what per-behavior statistics need, because "first trigger wins" would censor the others. `portfolio`: applies `combine`, `max_trades_per_zone` and the one-position limit to produce a realistic trade sequence and the equity simulation. Shadow trades inside one episode are strongly correlated; the day-block bootstrap (7.4) accounts for that.
- Risk sizing is not part of results; all metrics are in R. `risk_pct` (0.1-0.3) is used only by the optional equity simulator.

### 4.6 Engine (`edgebench.engine`)

`run(config, instrument, split) -> RunOutput`. It merges the M1 stream with derived M3/H1 completion events in the order of 2.1 and feeds `History` objects that cannot return data after the current bar (they raise `FutureAccessError`). The streaming engine is the reference implementation. A vectorized or numba fast path may be added only with an equivalence test against the reference on synthetic and fixture data. Detection results are cached by the hash of the sub-config that affects them.

### 4.7 Evaluator (optional AI layer)

- `describe(candidate) -> str`: deterministic text built only from data with `ts_close <= ts_decision` of the candidate: ATR-normalized last N M1/M3 bars (body, wicks, close position), zone geometry, observations, session, distances to targets. No images.
- `Evaluator` protocol: `evaluate(text, prompt_version) -> EvalResult{take, triggers, context_score 1..3, confidence, rationale}`. Backends selected by config: `opencode_cli`, `anthropic_api`, `openai_compatible`, `mock`. Results are cached in SQLite by `(candidate_id, prompt_version, model_id, text_hash)`. Prompts are versioned files in `prompts/` and never edited in place.
- **Acceptance:** agreement with blind human labels on events not used to design the prompt (Cohen's kappa with an interval) **and** out-of-sample lift `E[R | take] - E[R]` with a block-bootstrap interval. Until both pass, evaluator output must not feed any decision.
- A leakage test asserts `describe(candidate)` is identical when data after `ts_decision` is removed.

## 5. Human labels

`labels/labels.csv`: `candidate_id, labeler, labeled_at, take, triggers, context_score, notes`.

Blind protocol: the labeling tool renders charts truncated at the candidate's `ts_decision`, in random order, with no outcome fields; about 10% duplicates measure self-consistency; labels are committed before outcomes are joined. This removes hindsight bias, which otherwise lets an evaluator look good by learning the outcome.

## 6. Configuration sketch

```yaml
version: 1
instruments: [EURUSD, GBPUSD, XAUUSD, US100, BTCUSDT, ETHUSDT, SOLUSDT, TONUSDT]
sessions: [london, ny_am, crypto_evening]      # names from config/sessions.yaml
zones:
  fvg: {enabled: true, min_size_atr_h1: 0.2, min_displacement_body_atr_h1: null,
        invalid_on: close_through, max_episodes: 1, max_age_h1_bars: 200}
  fractal: {enabled: true, left: 2, right: 2,
            invalid_on: close_through, max_episodes: 1, max_age_h1_bars: 200}
  episode_gap_bars: 5
  window_bars: 30
patterns:
  sweep: {enabled: true, references: [h1_fractal, ltf_fractal_m1], min_depth_atr_m1: 0.1, max_return_bars: 3}
  stall: {enabled: true, n_bars: 3, max_range_atr_m1: 0.5}
  rejection: {enabled: true, min_wick_ratio: 0.6, close_zone: 0.33}
  inside: {enabled: true, mode: range, min_count: 1}
entry:
  triggers: [sweep, rejection, stall, inside]
  combine: first
  policy: market_next_open
  stop_buffer: {spreads: 1.0, atr_m1: 0.0}
  min_stop_spreads: 5
  max_stop_atr_h1: 0.5
  max_trades_per_zone: 1
exits:
  max_hold_minutes: 360
  ladder_r: [1, 2, 3, 5, 8, 10, 15]
risk: {risk_pct: 0.2}
```

## 7. Experiment protocol

### 7.1 Splits

`config/splits.yaml` defines `dev`, `holdout` (the last 20-25% of the horizon), walk-forward folds inside dev, and `embargo_days`. Events whose outcome window crosses a split boundary are dropped.

### 7.2 Holdout guard

The loader refuses `split=holdout` unless `EDGEBENCH_HOLDOUT_TOKEN` is set in the owner's shell. Every holdout run is appended to `holdout/ledger.jsonl` (time, config hash, code commit, reason). Holdout results are not written to `reports/`, which agents read. The runner environment never has the token.

### 7.3 Hypotheses and trial counting

`hypotheses/H-NNN.md` is written **before** running: slice definition, primary metric, decision rule, minimum n. `runs/ledger.jsonl` records every run, and reports print "trials so far: K" next to any headline number, because the more variants are tried the more a good-looking one is expected by chance.

### 7.4 Statistics

- Unit: R net of costs per trade. Report n, mean R, median R, share of trades >= 5R, max drawdown in R, profit factor (secondary), distribution of `cost_r`.
- Intervals: block bootstrap over trading days (events cluster in time, so an i.i.d. bootstrap is too optimistic).
- **Mandatory baselines:** B0 random entries inside the same zones and time windows with a matched stop-width distribution; B1 take the first touch with the same stop rule; B2 trigger labels shuffled within instrument and session. "Edge" always means relative to these.
- Long and short are reported separately (a trend in the sample can fake a one-sided edge), plus per instrument and per session. Slices with `n < n_min` (default 50) are printed as insufficient.
- Cost sensitivity: reruns with spread x1.5 and x2 and slippage x2. A micro-stop makes cost a large fraction of R, so this is a headline table, not an appendix.

## 8. Repository layout

```
AGENTS.md          standing instructions for worker agents (opencode)
ARCHITECT.md       standing instructions for the architect role (Claude)
docs/              this contract and design notes
config/            strategy_*.yaml, instruments.yaml, sessions.yaml, splits.yaml
src/edgebench/     contracts, data, zones, patterns, strategy, execution, engine,
                   outcomes, report, evaluator, labels, holdout, pack, runner, cli
tests/             unit tests, fixtures/ (protected)
tools/             download and probe scripts run on the owner's machine
gates/             gate scripts (protected)
tasks/             work queue (section 9.2)
experiments/       queue of configs to run
hypotheses/        declared before running
reports/           run reports, escalations (dev metrics only)
runs/              ledger and run manifests
labels/            human labels
prompts/           versioned evaluator prompts
pack/              generated context packs
holdout/           ledger.jsonl only; no data
data/              git-ignored
```

## 9. Automation protocol

### 9.1 Roles

- **Architect (Claude).** Owns `docs/`, `src/edgebench/contracts/`, `gates/`, `tests/fixtures/`, `src/edgebench/runner/`, `tasks/`, `hypotheses/`. When the repository is attached to the chat, the architect commits directly to `main`; otherwise it delivers a bundle (9.5).
- **Workers (opencode agents).** Execute tasks on branches `agent/<task-id>`.
- **Owner.** Holds the holdout token, labels events, approves hypotheses and contract changes, supplies the open decisions.

### 9.2 Task file

`tasks/T-NNN-slug.md` with YAML front matter and a markdown body:

```yaml
id: T-007
title: Implement FVG detector
status: pending                 # pending | blocked | done (desired state, architect-owned)
agent: flash-text               # flash-text | flash-vision
depends_on: [T-003]
allowed_paths: [src/edgebench/zones/fvg.py, tests/zones/test_fvg.py]
context_files: [docs/CONTRACT.md, src/edgebench/contracts/zone.py]
acceptance: ["pytest tests/zones/test_fvg.py -q", "edgebench gates --quick"]
max_attempts: 3
```

Runner-local state (attempts, in progress) lives in an untracked `.runner/` folder, so statuses in git never conflict.

### 9.3 Runner (`edgebench loop`)

1. Pull `main`; pick the first `pending` task whose dependencies are `done`.
2. Create `agent/<task-id>`; run the worker headless with one fixed prompt: "Follow AGENTS.md and execute tasks/<id>.md". If `.runner/feedback.md` exists the worker reads it first.
3. Check the diff against `allowed_paths` and the protected paths; run the gates and the task's `acceptance` commands.
4. On failure write the log to `.runner/feedback.md` and retry up to `max_attempts`; then set `blocked` and write `reports/escalations/<id>.md` (what was tried, logs, the question).
5. On success rebase on `main`, rerun the quick gates, fast-forward merge, mark the task `done`, push.
6. When the queue is empty or blocked, run `edgebench pack` and push `pack/latest.md`.

The owner never writes per-task prompts.

### 9.4 Gates

| id | check |
|---|---|
| G1 | `ruff check` and `ruff format --check` |
| G2 | `mypy` (strict on `contracts`) |
| G3 | unit tests |
| G4 | causality: for random cut points, objects with `known_at <= cut` are identical between a run on the truncated data and a run on the full data (synthetic data) |
| G5 | determinism: two runs give identical output hashes |
| G6 | every `config/*.yaml` validates against the schema |
| G7 | worker branches did not change protected paths |
| G8 | hygiene: no data files, no file over 1 MB outside an allowlist, no secret patterns |
| G9 | the task's own acceptance commands |

Protected paths: `gates/`, `tests/fixtures/`, `docs/`, `tasks/`, `hypotheses/`, `src/edgebench/contracts/`, `src/edgebench/runner/`, `holdout/`, `.github/`, `AGENTS.md`, `ARCHITECT.md`. Only the runner changes a task's status, never the worker. A worker that needs a change in a protected path escalates instead of editing.

### 9.5 Bundle fallback (no repository access in the chat)

Diffs written by a language model often fail to apply, so the bundle uses whole-file and exact-match operations:

```
EDGEBENCH-BUNDLE v1
base: <commit sha the architect read>
--- WRITE path
<full file content>
--- REPLACE path
<<<<<<< old
exact old text, must match exactly once
=======
new text
>>>>>>> new
--- DELETE path
--- END
```

`edgebench apply` reads the clipboard or a file in `inbox/`, checks `base` against `main` (warns when stale), applies on `architect/<timestamp>`, runs the gates, and merges or reports why not. When the architect reads the repository through links, it uses permalinks with a commit sha (`raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>`) so cached branch URLs cannot show a stale file.

### 9.6 Context pack

`pack/latest.md`, capped at about 30 KB: commit sha, task table, summaries of the last runs (metric tables with intervals and trial count), open escalations, hypothesis status, permalinks to the files the architect needs, and one explicit question or decision request.

### 9.7 Agent profiles

`config/agents.yaml` maps task types to worker profiles: bulk code and tests to the text-only model with large limits; rendering checks and rare visual sanity checks to the vision model with small limits; evaluator inference to whichever backend `evaluator.backend` selects. Charts are never read by OCR; the evaluator reads the text from `describe()`.

## 10. Milestones

| id | content | main author | acceptance |
|---|---|---|---|
| M0 | scaffold: pyproject, package skeleton, contracts, config schema, gates, runner skeleton, AGENTS.md, ARCHITECT.md, CI workflow | architect | `edgebench gates` green on the empty skeleton |
| M1 | data: loaders, resample, manifest, synthetic generator | architect core, workers parsers | loader and resample tests, ms/us detection, gap handling |
| M2 | zones and touch episodes, zone rendering for visual check | architect + workers | fixtures with known zones, G4 passes |
| M3 | pattern detectors | workers, architect review | fixtures per detector, G4 passes |
| M4 | execution, engine, ladder, events table | architect | fill table test, determinism, ambiguity tests |
| M5 | reports, baselines, bootstrap, holdout guard, hypothesis ledger | workers, architect review | report on synthetic data with known answer |
| M6 | blind labeling tool, `describe`, evaluator backends | workers | leakage test, mock backend end to end |
| M7 | research loop: pack, escalations, experiment queue | architect + workers | one full cycle with no manual prompt |

CI (GitHub Actions, free for public repositories) runs G1-G6 and G8 on synthetic data. Full backtests on real data run locally.

## 11. Open decisions

| id | question | default |
|---|---|---|
| D1 | fractal definition | left/right 2/2 |
| D2 | when an FVG stops being valid | `close_through`, one episode |
| D3 | session windows (London, NY AM, crypto evening) | owner supplies |
| D4 | exits | R ladder plus liquidity-target policy, `max_hold_minutes` 360 |
| D5 | entry policy | `market_next_open` |
| D6 | trades per zone | 1 |
| D7 | data horizon | up to 4 years, at least 12 months |
| D8 | forming H1 candle visible to the strategy | no |
| D9 | index data | US100 CFD |
| D10 | news blackout filter | off in v0, calendar CSV hook ready |
