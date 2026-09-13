# Autonomous FPL Optimizer

Autonomous Fantasy Premier League management system designed to optimize transfers, starting lineups, captaincy, and bench order for team Overspent FC (Team ID: 6834344).

The system maximizes expected points over a rolling multi-gameweek horizon while adhering to strict FPL rules, budget constraints, formation legality, and risk management policies.

---

## Core Capabilities

- Strategic Optimization Engine: Computes expected points (xP) using historical form, ICT index, fixture difficulty (FDR), home/away weighting, expected minutes, and injury risks.
- Squad and Formation Legality: Enforces official FPL constraints: 15-player squad (2 GKP, 5 DEF, 5 MID, 3 FWD), max 3 players per club, budget limits, and valid formations (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD).
- Subs Lineup Sequence Optimization: Analyzes appearance probability and tactical autosub value to order the bench (Slot 12: Goalkeeper sub; Slots 13-15: Outfield subs in descending expected arrival value).
- Chip Strategy Advisory: Evaluates high-leverage double gameweeks (DGW), blank gameweeks (BGW), and fixture swings to recommend Wildcard, Free Hit, Triple Captain, or Bench Boost only when expected value exceeds conservative thresholds.
- Dual-Mode Web Dashboard: Interactive dashboard serving either live via FastAPI (`localhost:8000`) or statically on GitHub Pages. Features toggles between Recommended Squad (with winning simulation xP), Actual Squad (matchday points), and Model Predicted xP.
- GitHub Actions Automation: Automated workflow evaluating deadline milestones (T-24h, T-6h, T-3h, T-90m, T-30m, T-15m) and routine refreshes every 30 minutes, deploying static dashboard updates to GitHub Pages.
- Audit Trail and Governance: Logs all decisions, constraint validations, and execution attempts to SQLite with cryptographic transaction hashes and approval gates for hits and chips.
- Historical Backtesting Engine: Evaluates algorithm decisions across previous gameweeks with zero lookahead bias against hold-squad baselines.

---

## System Architecture

```
fpl-bot/
├── .github/workflows/
│   └── optimizer.yml          # GitHub Actions scheduled workflow & Pages deployment
├── fpl_bot/
│   ├── agents/
│   │   ├── orchestrator.py    # Main workflow coordinator and stage controller
│   │   ├── strategist.py      # Transfer, chip, and squad optimization algorithms
│   │   ├── player_data.py     # Live FPL API client and statistical modeling
│   │   └── executor.py        # Safe transfer and lineup submission engine
│   ├── core/
│   │   ├── config.py          # Configuration and environment settings
│   │   ├── database.py        # SQLite persistence and audit logging
│   │   ├── models.py          # Pydantic data schemas
│   │   └── backtest.py        # Historical backtesting simulation engine
│   ├── services/
│   │   ├── fpl_api.py         # Official Fantasy Premier League REST client
│   │   ├── scheduler.py       # Dynamic deadline countdown scheduler
│   │   └── static_export.py   # Static bundle generator for GitHub Pages
│   ├── web/
│   │   ├── app.py             # FastAPI REST endpoints
│   │   └── templates/
│   │       └── index.html     # Dual-mode responsive web dashboard
│   └── cli.py                 # Command line interface
├── tests/                     # Unit and integration test suite
├── main.py                    # Application entrypoint
├── pyproject.toml             # Package specification and dependencies
└── README.md
```

---

## Installation

### Prerequisites

- Python 3.12 or newer
- Git

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/mraabhijit/fpl-bot.git
   cd fpl-bot
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the package with dependencies:
   ```bash
   pip install --upgrade pip
   pip install -e ".[test]"
   ```

---

## Configuration

Settings can be specified via environment variables or a `.env` file in the project root:

| Variable | Description | Default |
|---|---|---|
| `FPL_TEAM_ID` | Your FPL entry / team ID | `6834344` |
| `FPL_EMAIL` | Official FPL login email | `""` |
| `FPL_PASSWORD` | Official FPL login password | `""` |
| `FPL_EXECUTION_MODE` | Execution safety mode (`DRY_RUN` or `LIVE`) | `DRY_RUN` |
| `FPL_TIMEZONE` | Local timezone for deadline calculations | `Asia/Kolkata` |
| `WEB_HOST` | Web dashboard binding host | `0.0.0.0` |
| `WEB_PORT` | Web dashboard binding port | `8000` |

Example `.env` configuration:
```env
FPL_TEAM_ID=6834344
FPL_EMAIL=your_email@example.com
FPL_PASSWORD=your_password
FPL_EXECUTION_MODE=DRY_RUN
FPL_TIMEZONE=Asia/Kolkata
```

---

## Command Line Usage

The CLI supports diagnostic checks, optimization runs, backtesting, local server hosting, static bundle export, and deadline scheduling.

### 1. Diagnostic Health Check
Inspect team status, bank, free transfers, chips, mini-leagues, and upcoming deadline:
```bash
python main.py diagnostic
```

### 2. Strategic Optimization
Execute the full optimization cycle and print recommended transfers, starting XI, subs sequence, and captaincy rationale:
```bash
python main.py optimize
```

### 3. Historical Backtesting
Run zero-leakage simulation across past gameweeks to verify strategy performance against squad-hold baseline:
```bash
python main.py backtest
```

### 4. Local Web Server
Launch the FastAPI web dashboard with live auto-refresh:
```bash
python main.py server
```
Open `http://localhost:8000` in your web browser.

### 5. Static Site Export
Export static HTML and JSON bundles into the `dist/` directory for deployment to GitHub Pages:
```bash
python main.py export --output-dir dist
```

### 6. Scheduled Milestone Evaluation
Evaluate distance to deadline and trigger stage optimization:
```bash
# Automatic stage detection based on minutes remaining
python main.py scheduled --stage auto

# Force execution regardless of deadline milestone
python main.py scheduled --stage primary --force
```

### 7. Adaptive Multi-Factor Differential Learning
Settle completed gameweek match telemetry, compute prediction residuals, and retrain the adaptive model using regularized Multi-Factor Ridge Regression:
```bash
# Retrain model on completed gameweeks using Multi-Factor Ridge Regression
python main.py retrain --gameweek 4

# Inspect gameweek error report, learned feature weights, elite consensus, and team form
python main.py differentials --gameweek 4
```

Features incorporated in weekly retraining:
- Historical Residual Prior: Empirical Bayes shrinkage over past gameweeks.
- Player Form Trajectory: Form acceleration and goal involvement efficiency delta (GI vs xGI).
- Team Form Dynamics: Rolling 3-match offensive potency and defensive fragility indices.
- Elite Crowd Consensus: Effective ownership ($EO^{\text{elite}}$) and captaincy concentration among top overall managers in the world (League 314).
- Market Transfer Momentum: Normalized net event transfer velocity from official telemetry.

All retrained checkpoints are bounded within $[-2.0, +2.0]$ points to prevent erratic swings while systematically correcting model bias. Retraining executes autonomously inside GitHub Actions runners during post-gameweek workflow runs, with model weights and the SQLite database cached across runs via `actions/cache@v4`.


---

## GitHub Actions & GitHub Pages

The repository includes an automated workflow (`.github/workflows/optimizer.yml`) that runs in GitHub Actions and deploys the static dashboard to GitHub Pages.

### Milestone Schedule

The GitHub Actions workflow runs every 30 minutes (`cron: '*/30 * * * *'`) and matches the dynamic deadline countdown against configured milestones:

- T-24h (Initial model run, initial squad review)
- T-6h (Press conference updates, injury refresh)
- T-3h (Primary decision run, hit/transfer recommendations)
- T-90m (Early lineup leak monitoring)
- T-30m (Final audit and safety verification)
- T-15m (Emergency lockout safeguard)
- Routine (Data synchronization and static dashboard build outside milestone windows)

### GitHub Pages Setup

1. In your GitHub repository, navigate to **Settings** -> **Pages**.
2. Under **Build and deployment** -> **Source**, select **GitHub Actions**.
3. (Optional) In **Settings** -> **Secrets and variables** -> **Actions**, add:
   - `FPL_EMAIL`
   - `FPL_PASSWORD`
   - `FPL_TEAM_ID`
   - `FPL_EXECUTION_MODE` (`DRY_RUN` recommended)
4. Push changes to `master` or trigger a manual run via the **Actions** tab using **Run workflow**.

The dashboard will be published at `https://<your-username>.github.io/<repo-name>/`.

---

## Testing

Run the automated test suite using pytest:

```bash
pytest tests/ -v
```

Test coverage includes:
- Web API routes and error handling
- Squad formation rules and constraint satisfaction
- Execution safety and role permissions
- Scoring models and risk penalty functions
- Subs lineup sequence priority
- Static site exporter and scheduled workflow checks

---

## Safety and Execution Policy

- Default Dry-Run: The system defaults to `FPL_EXECUTION_MODE=DRY_RUN`. No live transfers or squad changes are submitted to the official FPL servers unless explicitly set to `LIVE`.
- Approval Gates: Recommended transfers incurring point hits (-4, -8) or chip activations require affirmative approval before submission.
- Cryptographic Audit Trail: Every recommendation and execution attempt generates a SHA-256 transaction hash stored in the SQLite database.
