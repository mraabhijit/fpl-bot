# Autonomous FPL Optimizer

Autonomous Fantasy Premier League management system designed to optimize transfers, starting lineups, captaincy, and bench order for team Overspent FC (Team ID: 6834344).

The system maximizes expected points over a rolling multi-gameweek horizon while adhering to strict FPL rules, budget constraints, formation legality, and risk management policies.

---

## Core Capabilities

- **Strategic Optimization Engine**: Solves integer programming formulations using PuLP to compute optimal transfers and starting lineups based on expected points (xP), fixture difficulty (FDR), home/away weighting, expected minutes, and injury risks.
- **Squad and Formation Legality**: Enforces official FPL constraints: 15-player squad (2 GKP, 5 DEF, 5 MID, 3 FWD), max 3 players per club, budget limits, and valid formations (1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD).
- **Subs Lineup Sequence Optimization**: Analyzes appearance probability and tactical autosub value to order the bench (Slot 12: Goalkeeper sub; Slots 13-15: Outfield subs in descending expected arrival value).
- **Chip Strategy Advisory**: Evaluates high-leverage double gameweeks (DGW), blank gameweeks (BGW), and fixture swings to recommend Wildcard, Free Hit, Triple Captain, or Bench Boost only when expected value exceeds conservative thresholds. Unobtrusive tooltip popover (`ℹ️`) explains chip recommendations without cluttering the UI.
- **Dual-Mode Web Dashboard**:
  - **Dark & Light Mode**: Integrated theme toggle with `localStorage` persistence and automatic system preference detection.
  - **Flat Modern Design**: Clean UI with fluid responsive layouts across desktop, tablet, and mobile screens.
  - **Collapsible Sections**: Accordions with animated chevron indicators for **Audit Trail** and **Historical Backtesting**.
  - **Team Form Dynamics**: Real Premier League club names (`Arsenal`, `Man City`, etc.) resolved in rolling form attack/defense leaderboards.
  - **Direct GitHub Actions Dispatch**: In-page "Run Optimizer" and "Run Backtest" buttons support ad-hoc workflow dispatching directly via GitHub REST API.
  - **Dual Serving**: Host locally via FastAPI (`localhost:8000`) or view static deployment on GitHub Pages.
- **Gated GitHub Actions Automation**: Replaced continuous intermediate builds with two focused milestones:
  1. **T-3h Transfer Deadline Milestone**: Executes primary optimization 3 hours before gameweek deadline.
  2. **00:00 IST Daily Refresh**: Re-run the optimizer with the latest results, prices and news, and republish the dashboard.
  - Automated workflow skips redundant builds and static site deployments when no milestone is due.
- **Trained Points Model (hybrid)**: Gradient boosting over point-in-time features (rolling minutes, xG/xA/bonus/saves per 90, team attack/defence form, opponent strength, venue, double gameweeks) with a hand-built heuristic as one of its features and as the benchmark to beat. Trained on the vaastav/Fantasy-Premier-League seasons plus the current season from the FPL API; news (injury/suspension) availability is applied on top at prediction time.
- **Integer-Programming Squad Optimizer**: A PuLP/CBC model picks the squad, XI, and captain together (budget, 2/5/5/3, max 3 per club, legal formations) and prices extra transfers at -4 each, so it chooses 0..N transfers and any hits on net expected gain. The same solver builds a fresh £100m squad for GW1 / Wildcard / Free Hit.
- **Walk-Forward Backtesting Engine**: Each gameweek the model is refit only on earlier gameweeks, the bot plays its own squad (free transfers, hits, captaincy, autosubs) against the real outcome, and prediction error is reported against baselines. See `python main.py backtest --season 2025-26`.
- **Audit Trail & Governance**: Logs all decisions, constraint validations, and execution attempts to SQLite with cryptographic SHA-256 transaction hashes.

---

## System Architecture

```
fpl-bot/
├── .github/workflows/
│   └── optimizer.yml          # GitHub Actions scheduled workflow & Pages deployment
├── fpl_bot/
│   ├── agents/
│   │   ├── orchestrator.py    # Main workflow coordinator and stage controller
│   │   ├── optimization_agent.py # Integer programming squad and transfer solver
│   │   ├── projection_agent.py   # Next-GW expected points (trained model via forecast_service) + legacy fallback
│   │   ├── chip_agent.py         # Long-range chip valuation and timing engine
│   │   ├── fixture_agent.py      # Fixture difficulty (FDR) and calendar analysis
│   │   ├── availability_agent.py # Injury, suspension, and press conference tracker
│   │   ├── rank_agent.py         # Mini-league and overall rank analytics
│   │   └── deadline_auditor.py   # Pre-deadline sanity and constraint auditor
│   ├── core/
│   │   ├── config.py          # Configuration and environment settings
│   │   ├── database.py        # SQLite persistence and audit logging
│   │   ├── models.py          # Pydantic data schemas
│   │   └── backtest.py        # Historical backtesting simulation engine
│   ├── services/
│   │   ├── fpl_api.py         # Official Fantasy Premier League REST client
│   │   ├── fpl_auth.py        # Authentication session management
│   │   ├── scheduler.py       # Dynamic deadline countdown and milestone scheduler
│   │   ├── static_export.py   # Static bundle generator for GitHub Pages
│   │   ├── notification_service.py # System alerts and webhook notifications
│   │   ├── transaction_service.py  # FPL live transfer and lineup submission
│   │   └── player_data.py     # Player statistics and feature extraction
│   ├── web/
│   │   ├── app.py             # FastAPI REST endpoints
│   │   └── templates/
│   │       └── index.html     # Dual-theme responsive web dashboard
│   └── cli.py                 # Command line interface
├── tests/                     # Unit and integration test suite (34 tests)
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
Run a walk-forward simulation of the current season (stored in the dashboard) or validate on a completed past season (needs no FPL API):
```bash
python main.py backtest                    # current season so far, compared with your real points
python main.py backtest --season 2025-26   # model vs heuristic vs form baselines: points, MAE, RMSE, Spearman
```
Season totals from a single simulated season are noisy (a few hundred points depending on retrain schedule); prefer the prediction-error columns and compare across seasons.

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
# Automatic stage detection based on milestones (T-3h or the 00:00 IST refresh)
python main.py scheduled --stage auto

# Force execution regardless of deadline timing
python main.py scheduled --stage primary --force
```

---

## GitHub Actions & GitHub Pages

The repository includes an automated workflow (`.github/workflows/optimizer.yml`) that runs in GitHub Actions and deploys the static dashboard to GitHub Pages.

### Milestone Schedule

The GitHub Actions workflow runs on an automated schedule:
- **Daily 00:00 IST (`18:30 UTC`)**: Refreshes the optimizer and dashboard with the day's results, prices and news.
- **Hourly Check (`0 * * * *`)**: Evaluates the upcoming gameweek deadline countdown and triggers the primary optimization cycle when within the **T-3h window** (150–210 minutes before deadline).
- **Elimination of Intermediate Builds**: Outside of these milestones, execution is skipped (`executed: false`), bypassing redundant test runs and static site builds to conserve GitHub Actions minutes.

### Manual Workflow Dispatch

Workflows can be manually triggered with custom inputs:
- From the GitHub Actions UI: Go to **Actions** -> **Autonomous FPL Optimizer** -> **Run workflow**.
- From the Dashboard: Click **Run Optimizer** or **Run Backtest** on the web page to trigger the workflow via the GitHub REST API.

### GitHub Pages Setup

1. In your GitHub repository, navigate to **Settings** -> **Pages**.
2. Under **Build and deployment** -> **Source**, select **GitHub Actions**.
3. (Optional) In **Settings** -> **Secrets and variables** -> **Actions**, add:
   - `FPL_EMAIL`
   - `FPL_PASSWORD`
   - `FPL_TEAM_ID`
   - `FPL_EXECUTION_MODE` (`DRY_RUN` recommended)
4. Push changes to `main` or trigger a manual run via the **Actions** tab.

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
- Static site exporter and milestone gating logic
- Responsive UI components, theme switching, and collapsible accordions

---

## Safety and Execution Policy

- **Default Dry-Run**: The system defaults to `FPL_EXECUTION_MODE=DRY_RUN`. No live transfers or squad changes are submitted to the official FPL servers unless explicitly set to `LIVE`.
- **Approval Gates**: Recommended transfers incurring point hits (-4, -8) or chip activations require affirmative approval before submission.
- **Cryptographic Audit Trail**: Every recommendation and execution attempt generates a SHA-256 transaction hash stored in the SQLite database.
