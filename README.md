# edgebench

A research bench for testing discretionary price-action ideas on historical data: write the rules down, detect events in code, backtest in R-multiples, and verify on data the rules were never tuned on.

Исследовательский стенд для проверки дискреционных price-action идей на истории: правила формализуются, события находит код, бэктест считается в R, проверка идёт на данных, на которых правила не подбирались.

## Idea

- **Context on H1:** fair value gaps (FVG) and fractal levels.
- **Behavior on M1-M3 at the zone:** sweeps, stalls, rejection wicks, inside-bar-like stalls. These are treated as different kinds of behavior when price arrives at a zone, not as steps of one chain.
- **Event-based dataset:** every touch of an H1 zone becomes one event with features (zone, session, instrument, stop width in ATR and in spreads) and an outcome measured in R.
- **Results by distribution, not win rate:** expectancy and tail of R per behavior type, session and instrument, with a realistic spread and execution model.
- **Optional LLM evaluator:** reads a text description of the event, never a chart image, sees only data available at decision time, and is checked against human labels on held-out events. Backends are swappable.
- **Holdout discipline:** a reserved period that tuning and automated research cannot read freely.

## Status

Early design stage. No code yet.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). You may use, modify and redistribute the project, but you must keep the copyright and attribution notices and state significant changes.

## Disclaimer

Research software. Nothing here is financial advice, and backtest results do not predict future performance.
