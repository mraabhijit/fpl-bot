# Changelog

## v2.0.0

A new prediction engine, optimizer and backtest, plus a dashboard that shows any gameweek.

### Added
- **Trained points model**: gradient boosting on point-in-time features (rolling player form, venue-split team attack and defence form, results form, Elo, points the opponent concedes to each position, FPL fixture difficulty), trained on the vaastav seasons plus the live season. News availability is applied on top.
- **Squad optimizer** (PuLP/CBC integer program) that picks squad, XI and captain together, prices extra transfers at -4 and can build a fresh £100m squad.
- **Walk-forward backtest** that only ever sees earlier gameweeks: `backtest --season 2025-26` reports points and prediction error against heuristic and form baselines.
- **Public squad state**: free transfers, bank and selling prices rebuilt from public history when no valid FPL token is available (matched the authenticated values exactly when checked).
- **Gameweek selector** on the Actual Team tab: real lineup and points (captain doubling and automatic substitutions applied) next to the model's frozen pre-deadline prediction, from the first stored prediction to the gameweek after the latest finished one.
- **Data freshness** banner and `generated_at` / `squad_source` fields in the diagnostic.
- CI: unit tests, install check and a backtest smoke test on pull requests; a manual FPL-token check workflow.

### Changed
- Squad value now shows FPL's market value with what the squad sells for underneath.
- Chips are tracked per half-season with the API's real chip names.
- Token refresh failures now say why.
- The version lives in one place (`settings.version`).

### Removed (breaking)
- The adaptive residual-learning model and everything built for it: the `retrain` and `differentials` commands, `/api/differentials` and `/api/retrain`, the dashboard card, the nightly settle-and-train step and the two database tables behind it.
- The greedy one-transfer search.

### Fixed
- Hardcoded home advantage, the 0.5-point expected-points floor, the 2024/25 club-id table, a missing `Tuple` import, and the dashboard reading a 10-minute-old cached copy of its data.
