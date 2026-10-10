# FPL Bot: guide for every session

Read this first. It records what the project is, the decisions already made and how we work, so a new session does not re-ask or re-derive them. Details of usage live in `README.md`; release notes in `CHANGELOG.md`.

## What this is
An autonomous Fantasy Premier League advisor for one team (Overspent FC, ID 6834344, repo `mraabhijit/fpl-bot`). After each gameweek it predicts every player's points for the next one and picks the squad, lineup, captain and transfers that maximise expected points. It publishes a dashboard on GitHub Pages and never makes transfers on its own (see Safety).

## Decisions already made (do not reopen without the user asking)
- **Goal**: best reward/cost: lineup, captain and hit-aware transfers for the next gameweek. Chips are advisory only.
- **Model**: hybrid. A heuristic xP is a feature and the benchmark; HistGradientBoosting predicts points per fixture, and a gameweek prediction is the sum over its fixtures (double gameweeks). News availability is applied on top, once.
- **Data**: vaastav Fantasy-Premier-League dataset for past seasons (`PAST_SEASONS` in `fpl_bot/data/history.py`) plus the live season from the FPL API. Ignore vaastav's `xP` column (corrupted in 2025-26).
- **Leak-free by construction**: features use only earlier gameweeks (`shift(1)`); `tests/test_features_leakage.py` guards this. Never add a feature without keeping that test green.
- **Optimizer**: PuLP/CBC integer program (`core/squad_solver.py`). Keep `pulp>=2.9,<3` (4.x changed the API). Hits cost 4, a used free transfer costs 0.6, bench weight 0.12. `free_transfers >= 15` means build from scratch (GW1, Wildcard, Free Hit).
- **Scope of rewrite**: core only. UI, scheduler and agent shell were kept.
- **Squad state without a token**: reconstructed from public history (`services/public_squad.py`: free transfers, bank, selling prices) and verified equal to `my-team`. `CurrentSquad.source` is `my-team` or `public-estimate`; the dashboard shows a freshness banner and a warning for estimates.
- **Two values**: squad value (market price) and sell value (selling prices, half of each rise rounded down) are shown separately.
- **Gameweek selector**: Actual Team tab lists every gameweek from the first stored prediction, and GWx+1 only once GWx has finished. Default is the latest FPL gameweek, partial points included. Pre-deadline predictions are frozen in `projection_snapshots` and never recomputed with hindsight.
- **Removed on purpose**: the adaptive-learning / differentials stack (trainer, settlement, consensus, team-form services, `/api/differentials`, `/api/retrain`, CLI `retrain` and `differentials`). Do not reintroduce it.
- **Deferred**: multi-gameweek planning (matters for long-term injuries). The user said "we will build it as it goes by"; do not start it unprompted.

## Workflow (strict)
1. Branch from `develop`: `feature/...`, `fix/...`, `chore/...`, `docs/...`.
2. Open a PR into `develop`. CI (`Tests and backtest smoke`) must pass. The user merges.
3. After merging, check that CI is green on `develop`. Only then open a PR `develop` → `main` (a release or a batch of changes). `main` needs a clean CI check; the user merges.
4. Never push directly to `develop` or `main`, and never merge PRs yourself.
5. If GitHub says a branch is out of date, merge the base into it (`git merge origin/main`) and push. When the user asks for the merge "as mraabhijit", use their own git identity with no Claude override.
6. CI does not check secrets. `Check FPL auth` is a manual workflow for that.

## Commits, PRs and releases
- Claude's commits: `git -c user.name=Claude -c user.email=noreply@anthropic.com commit ...`, ending with the `Co-Authored-By` trailer from the session's attribution reminder. PR bodies end with the `Generated with Claude Code` line.
- Conventional-style subjects (`feat:`, `fix:`, `chore:`, `docs:`, `chore(release):`).
- Release: bump `pyproject.toml` version and `fpl_bot/core/config.py` (`version = "vX.Y.Z"`; the API app strips the `v`), add a `CHANGELOG.md` section, ship through develop → main, then tag `vX.Y.Z` on the main merge commit and publish a GitHub release with the changelog section as notes. Tagging and releasing are visible on the repo: do them only when the user says go. Current version: v2.0.0.

## Working conventions
- Python 3.12, virtualenv in `.venv`. Run `.venv/bin/python -m pytest` (about 67 tests) before every PR. Backtest: `python main.py backtest --season 2025-26`.
- `fpl_bot/cli.py`, `fpl_bot/agents/projection_agent.py` and `fpl_bot/core/models.py` use CRLF line endings. Preserve them (scripted edits often convert to LF; check with `git diff --stat`).
- Follow the surrounding code's style and comment density. Add tests for new logic, including leakage tests for new features.
- Verify the exported dashboard with jsdom when changing `fpl_bot/web/templates/index.html`. Static fetches use `cache: 'no-store'` because Pages serves `max-age=600`.
- Do not trust claims about the deployment from memory: read the live Pages JSON (`data/*.json`) and the `generated_at` / `data_as_of_gw` fields.
- Untracked local files (`corrections.md`, `FPL-Optimizer.md`, `.env`, `dist/`, `errors/`) are not part of the repo; do not commit them.

## Secrets and auth
- `FPL_ACCESS_TOKEN` and `FPL_REFRESH_TOKEN` are repo secrets used by `optimizer.yml`. The access token lasts 1 hour; the refresh token is single-use and returned `invalid_grant`, so it cannot renew. Expect the deployment to fall back to the public estimate until the user updates the secret.
- `scripts/check_secrets.py` only reads (never refreshes). Never print, log or commit tokens. A tokens write to the secret store needs the user to do it.
- Copy tokens from DevTools in full: a truncated copy contains `…` (U+2026) and fails.

## Known limits
- The backtest has no point-in-time injury news.
- Free-transfer top-ups granted by FPL outside the normal rules are invisible in public history.
- Prediction history (`projection_snapshots`) lives in the SQLite DB restored by an Actions cache.
- One gameweek at a time (see Deferred).

## Safety
The bot recommends; it does not execute transfers (`DRY_RUN` semantics stay on). Anything that writes to the user's FPL account, GitHub secrets, branch rules or releases needs explicit user approval.
