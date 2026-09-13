# Autonomous Fantasy Premier League Optimizer

## 1. Mission

Build an autonomous Fantasy Premier League decision system whose sole objective is to maximize expected FPL points and improve rank over the full season.

FPL team ID:

**6834344**

Team name:

**Overspent FC**

Season:

**2026/27**

Primary objectives:

1. Maximize expected points.
2. Aggressively improve overall rank.
3. Simultaneously compete in the user's mini-leagues.
4. Optimize over the full remaining season, not merely the next Gameweek.
5. Use chips aggressively when the expected value justifies them.
6. Prefer free transfers.
7. Hits require explicit user approval.
8. Chips require explicit user approval.

Do not optimize for aesthetics, player popularity, template conformity, or minimizing risk unless those factors affect expected points/rank.

---

# 2. Core architecture

Implement the system as multiple specialized agents coordinated by an Orchestrator.

```text
                    ┌────────────────────┐
                    │     Scheduler      │
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │    Orchestrator    │
                    └─────────┬──────────┘
                              │
          ┌───────────────────┼────────────────────┐
          ▼                   ▼                    ▼
 ┌────────────────┐  ┌────────────────┐  ┌────────────────┐
 │ Projection     │  │ Fixture        │  │ Availability   │
 │ Agent          │  │ Agent          │  │ Agent          │
 └───────┬────────┘  └───────┬────────┘  └───────┬────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
                    ┌────────────────────┐
                    │ Optimization Agent│
                    └─────────┬──────────┘
                              │
                              ▼
                    ┌────────────────────┐
                    │ Deadline Auditor   │
                    └─────────┬──────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             Routine actions      Hit / chip
             can proceed          approval required
                    │                   │
                    └─────────┬─────────┘
                              ▼
                       FPL Execution
```

---

# 3. FPL data layer

Use the FPL API at:

`https://fantasy.premierleague.com/api/`

The API is undocumented by FPL itself, so all parsers must be defensive and version-tolerant.

Important public endpoints include:

* `/bootstrap-static/`
* `/fixtures/`
* `/fixtures/?event={GW}`
* `/event/{GW}/live/`
* `/entry/{TEAM_ID}/`
* `/entry/{TEAM_ID}/history/`
* `/entry/{TEAM_ID}/transfers/`
* `/entry/{TEAM_ID}/event/{GW}/picks/`
* `/element-summary/{PLAYER_ID}/`
* `/leagues-classic/{LEAGUE_ID}/standings/`

Public endpoints should be used wherever possible. Cache aggressively and avoid unnecessary requests because the API does not publish an official rate limit.

---

# 4. Authentication

Do NOT store the user's FPL password.

Use the official FPL login/authentication flow and securely persist the resulting authenticated session/token required for private actions.

Authentication must be isolated in a dedicated `FPLAuthService`.

Never expose authentication cookies/tokens to the LLM prompt.

Never log authentication credentials.

Provide:

```text
fpl_auth/
    login
    refresh
    validate_session
    logout
```

If authentication expires, stop execution and request re-authentication rather than attempting unsafe workarounds.

---

# 5. Team data

On every run retrieve and validate:

* team ID
* manager name
* current Gameweek
* overall rank
* overall points
* team value
* bank
* free transfers
* transfer history
* current squad
* current starting XI
* bench order
* captain
* vice-captain
* available chips
* used chips
* current mini-leagues
* mini-league standings

The `/entry/{id}/` and related endpoints provide manager, history, picks, transfers and league information.

Never make a recommendation using stale squad data.

---

# 6. Projection Agent

Purpose:

Estimate each player's expected FPL points for:

* next Gameweek
* next 3 Gameweeks
* next 5 Gameweeks
* next 8 Gameweeks

Create a player projection containing:

```text
expected_minutes
expected_starts
expected_goals
expected_assists
expected_clean_sheet_probability
expected_bonus
expected_cards
expected_goals_conceded
expected_penalty_probability
expected_set_piece_probability
expected_fpl_points
confidence
```

Use multiple evidence sources where available.

Weight:

1. Recent underlying performance
2. Season performance
3. Expected minutes
4. Fixture quality
5. Team attacking strength
6. Team defensive strength
7. Player role
8. Set pieces
9. Penalties
10. Rotation risk
11. Injury status
12. Manager/team tactical changes

Do NOT simply rank players by current FPL points.

---

# 7. Fixture Agent

Calculate fixture strength for every club.

Consider:

* opponent strength
* home/away
* attacking matchup
* defensive matchup
* fixture congestion
* blanks
* doubles
* postponements
* future fixture swings

Produce:

```text
fixture_score_1GW
fixture_score_3GW
fixture_score_5GW
fixture_score_8GW
```

Do not use a static fixture-difficulty rating as the sole input.

---

# 8. Availability Agent

Continuously evaluate:

* injuries
* suspensions
* minutes restrictions
* rotation
* press-conference information
* predicted lineups
* European fixture congestion
* international duty
* manager comments
* late-breaking team news

Every player should receive:

```text
availability_probability
start_probability
minutes_probability
rotation_risk
injury_risk
```

The final deadline run must override older assumptions when credible new information becomes available.

---

# 9. Rank / Mini-League Agent

Track both:

### Overall rank

Monitor:

* current rank
* recent rank movement
* points required to gain meaningful rank positions
* ownership of key players
* effective ownership where available

### Mini-leagues

For each important mini-league:

* identify league position
* identify nearest rivals
* calculate points gap
* identify rival-owned players
* identify useful differentials
* identify whether aggressive moves are justified

Overall rank and mini-league performance have equal strategic importance.

---

# 10. Optimization Agent

This is the main decision engine.

For every Gameweek, evaluate:

### A. Hold

Calculate expected points if no transfer is made.

### B. Free transfer

Calculate expected points after each viable free-transfer combination.

### C. Hit

Calculate expected points after taking a -4, -8, etc.

A hit should only be recommended when:

```text
future_expected_gain
+
expected_minutes_gain
+
fixture_gain
+
structural_gain
>
hit_cost
+
future_transfer_opportunity_cost
```

Do not recommend hits merely because a player is projected to score slightly more.

### D. Captain

Evaluate all realistic captain candidates.

Calculate:

```text
captain_expected_points
captain_floor
captain_ceiling
ownership
effective_ownership
fixture
minutes_probability
```

Select the captain that maximizes the objective function, not automatically the highest-owned player.

### E. Bench

Optimize bench order using:

* expected points
* start probability
* autosub probability
* formation constraints

### F. Formation

Select the formation producing the highest expected total.

---

# 11. Chip optimizer

Available chips must be tracked individually.

Evaluate:

* Wildcard
* Free Hit
* Bench Boost
* Triple Captain
* any new/current-season chips exposed by the API

For each chip calculate:

```text
immediate_expected_gain
future_expected_gain
opportunity_cost
fixture_context
blank_context
double_gameweek_context
squad_structure_gain
remaining_season_value
```

Do not automatically save chips until late season.

The user's preference is aggressive chip usage.

However:

**A chip must never be activated automatically.**

The bot may recommend a chip and request approval.

---

# 12. Full-season planning

Do not optimize only one Gameweek.

Maintain rolling projections over:

* GW+1
* GW+2
* GW+3
* GW+4
* GW+5
* GW+6
* GW+7
* GW+8

Use longer horizons for:

* Wildcard decisions
* major structural transfers
* expensive premiums
* goalkeeper combinations
* defensive rotations

Use shorter horizons for:

* captaincy
* bench decisions
* injury replacements
* late team news

---

# 13. Differential strategy

Because the user's objective is aggressive rank climbing, calculate:

```text
differential_value =
expected_points *
(1 - ownership_adjustment)
```

But do NOT chase differentials for their own sake.

A differential should be selected only when its expected value exceeds the safer alternative by a meaningful margin.

Distinguish:

```text
good differential
```

from

```text
lottery differential
```

Never select a low-probability player solely because ownership is low.

---

# 14. Decision objective

Create a configurable scoring function:

```text
UTILITY =
expected_points
+ rank_gain_value
+ mini_league_gain_value
+ future_squad_value
+ flexibility_value
- hit_cost
- transfer_opportunity_cost
- rotation_risk_penalty
- injury_risk_penalty
```

Weights should be configurable in one settings file.

Default objective:

```text
overall_rank_weight = 1.0
mini_league_weight = 1.0
short_term_points = high
long_term_value = high
risk_tolerance = aggressive
free_transfer_preference = high
hit_tolerance = medium
chip_aggression = high
```

---

# 15. Scheduler

Do NOT hard-code a weekly weekday/time.

The FPL Gameweek deadline must be retrieved dynamically.

Every week:

```text
deadline = current_FPL_GW.deadline_time

analysis_time = deadline - 3 hours
```

Use the FPL deadline itself as the source of truth.

The scheduler must handle:

* Saturday deadlines
* Sunday deadlines
* Monday deadlines
* midweek deadlines
* blank Gameweeks
* double Gameweeks
* postponed fixtures

Also create a final audit shortly before the actual deadline.

Recommended sequence:

```text
T - 24h:
Initial analysis

T - 6h:
Refresh projections and news

T - 3h:
Primary decision run

T - 90m:
Re-check injuries/lineups/news

T - 30m:
Final audit

T - 15m:
Execution safety check

T - deadline:
No new action unless explicitly configured
```

The user has requested the primary bot run **3 hours before the deadline**, Asia/Kolkata.

---

# 16. Execution permissions

Create an explicit policy engine.

### Automatically allowed

* Starting XI changes
* Bench order
* Captain
* Vice-captain
* Free transfers

### Approval required

* Any transfer requiring a hit
* Any chip activation
* Any action exceeding the predefined transfer budget

### Never allowed

* Any action when authentication is uncertain
* Any action after the deadline
* Duplicate transfer submission
* Transfer based on stale data
* Chip activation without confirmation
* Hit without confirmation

---

# 17. Approval workflow

When approval is required, send:

```text
ACTION REQUIRED

Gameweek: GW__
Deadline: __

Proposed action:
OUT: Player A
IN: Player B

Cost:
-4 points

Expected gain:
+X.X points

Expected net gain:
+Y.Y points

Why:
1. ...
2. ...
3. ...

Risk:
...

Alternative:
...

Approve hit?
[YES]
[NO]
```

For chips:

```text
CHIP APPROVAL REQUIRED

Chip: Wildcard

Expected immediate gain: +X.X
Expected 5-GW gain: +Y.Y
Expected opportunity cost: Z.Z

Reason:
...

Approve?
[YES]
[NO]
```

Never interpret silence as approval.

---

# 18. Deadline Auditor

The Deadline Auditor is the final authority before execution.

It must re-fetch:

* current Gameweek
* deadline
* squad
* free transfers
* bank
* current player availability
* fixtures
* captain
* transfer status
* chip availability

Then verify:

```text
Is deadline still open?
Is authentication valid?
Is squad state unchanged?
Is proposed transfer legal?
Is budget sufficient?
Is formation legal?
Is captain legal?
Is chip still available?
Has another process already submitted a transaction?
```

If any check fails:

**STOP.**

Do not execute.

---

# 19. Transaction safety

Every transaction must use an idempotency mechanism.

Before submitting:

```text
transaction_hash =
hash(
    team_id,
    gameweek,
    transfer_list,
    captain,
    vice_captain,
    bench_order,
    chip
)
```

Store executed hashes.

Never submit the same transaction twice.

After submission, re-read the FPL team state and verify that the intended action actually occurred.

---

# 20. Database

Use PostgreSQL or SQLite initially.

Tables:

```text
teams
players
fixtures
gameweeks
player_projections
player_availability
team_snapshots
transfers
recommendations
approvals
executions
chips
league_standings
scheduler_runs
audit_logs
```

Keep historical projections so the bot can measure whether its forecasts are actually accurate.

---

# 21. Backtesting

Before allowing live execution, implement a backtesting engine.

Test historical Gameweeks using only information that would have been available at the decision time.

Measure:

* expected points vs actual points
* transfer success
* hit ROI
* captain success
* chip ROI
* rank change
* mini-league change
* projection calibration
* minutes prediction accuracy

Do not allow future information to leak into historical decisions.

---

# 22. Observability

Every weekly decision must produce an audit record.

Example:

```text
GW12 DECISION AUDIT

Initial squad:
...

Candidate transfers:
1. ...
2. ...
3. ...

Selected:
...

Expected points:
...

Captain:
...

Vice:
...

Bench:
...

Chip decision:
...

Hit decision:
...

Reasons:
...

Data timestamp:
...

Execution timestamp:
...

Result:
...
```

This is mandatory.

---

# 23. Failure behavior

If any required data source fails:

```text
FAIL SAFE
```

Do not guess.

Examples:

* FPL API unavailable
* authentication expired
* player data stale
* deadline cannot be verified
* squad cannot be verified
* conflicting team state
* fixture data missing
* transaction response ambiguous

In these cases, notify the user instead of executing.

---

# 24. Technology recommendation

Preferred stack:

```text
Python 3.12+

FastAPI
PostgreSQL
APScheduler or equivalent dynamic scheduler
httpx
Pydantic
Redis optional
Docker
```

Use an LLM only where reasoning is useful.

Do NOT make the LLM responsible for:

* arithmetic
* budget validation
* formation legality
* transaction idempotency
* deadline calculations
* API authentication
* database consistency

Those must be deterministic code.

The LLM should interpret qualitative information and assist with strategic reasoning.

---

# 25. Agent separation

Implement these modules:

```text
agents/
    orchestrator.py
    projection_agent.py
    fixture_agent.py
    availability_agent.py
    rank_agent.py
    optimization_agent.py
    chip_agent.py
    deadline_auditor.py
```

Services:

```text
services/
    fpl_api.py
    fpl_auth.py
    player_data.py
    fixture_service.py
    news_service.py
    scheduler.py
    transaction_service.py
    notification_service.py
```

Core:

```text
core/
    models.py
    scoring.py
    constraints.py
    permissions.py
    risk.py
    backtest.py
```

---

# 26. Gemini implementation order

Build in this order.

### Phase 1 — Read-only FPL integration

Implement:

* authentication
* team 6834344 lookup
* bootstrap data
* current Gameweek
* fixtures
* squad
* history
* transfers
* leagues
* player summaries

Do not execute transactions yet.

### Phase 2 — Decision engine

Implement:

* projections
* fixtures
* availability
* optimization
* captain
* bench
* transfer evaluation
* chip evaluation

### Phase 3 — Backtesting

Validate the strategy against historical data.

### Phase 4 — Dry-run automation

Run automatically but execute nothing.

Produce the weekly recommended team.

### Phase 5 — Approval system

Add explicit approval for hits and chips.

### Phase 6 — Live execution

Enable:

* free transfers
* lineup
* captain
* bench

Then separately enable hit/chip execution only after explicit approval.

---

# 27. Critical safety rule

The system must never interpret an optimization recommendation as authorization to execute.

Separate:

```text
RECOMMENDATION
```

from:

```text
AUTHORIZATION
```

from:

```text
EXECUTION
```

These are three different states.

---

# 28. First successful run

The first run should be diagnostic only.

It should output:

```text
FPL CONNECTION: OK
TEAM ID: 6834344
TEAM NAME: Overspent FC
CURRENT GW: ...
DEADLINE: ...
TIMEZONE: Asia/Kolkata

OVERALL RANK: ...
OVERALL POINTS: ...
TEAM VALUE: ...
BANK: ...
FREE TRANSFERS: ...

CURRENT XI:
...

BENCH:
...

CAPTAIN:
...
VICE:
...

AVAILABLE CHIPS:
...

MINI-LEAGUES:
...

AUTHENTICATED WRITE ACCESS:
YES/NO

EXECUTION MODE:
DRY RUN
```

Do not make any transfer during this diagnostic run.

---

# 29. Final requirement

The finished bot must be able to answer this question every Gameweek:

> "Given the current squad, budget, free transfers, fixtures, player availability, predicted minutes, projected points, rank situation, mini-league situation, future fixture schedule and remaining chips, what sequence of actions maximizes expected season outcome?"

It must then produce:

1. Transfers
2. Starting XI
3. Bench order
4. Captain
5. Vice-captain
6. Chip recommendation
7. Hit recommendation
8. Expected points
9. Risk assessment
10. Explanation
11. Required approval
12. Execution status

Build for **Overspent FC — Team 6834344 — 2026/27**.
