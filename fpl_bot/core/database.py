"""
SQLite database storage for state, history, recommendations, approvals, and audit logs.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional
from fpl_bot.core.config import settings


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Initializes all tables required by Section 20 of FPL-Optimizer.md."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Teams
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                short_name TEXT NOT NULL,
                strength INTEGER,
                strength_attack_home INTEGER,
                strength_attack_away INTEGER,
                strength_defence_home INTEGER,
                strength_defence_away INTEGER,
                raw_data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Players
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY,
                web_name TEXT NOT NULL,
                first_name TEXT,
                second_name TEXT,
                team_id INTEGER,
                element_type INTEGER,
                now_cost INTEGER,
                status TEXT,
                news TEXT,
                chance_of_playing_this_round INTEGER,
                form REAL,
                total_points INTEGER,
                selected_by_percent REAL,
                raw_data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Fixtures
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS fixtures (
                id INTEGER PRIMARY KEY,
                event INTEGER,
                team_h INTEGER,
                team_a INTEGER,
                team_h_difficulty INTEGER,
                team_a_difficulty INTEGER,
                kickoff_time TEXT,
                finished BOOLEAN,
                started BOOLEAN,
                team_h_score INTEGER,
                team_a_score INTEGER,
                raw_data TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Gameweeks
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS gameweeks (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                deadline_time TEXT NOT NULL,
                is_current BOOLEAN,
                is_next BOOLEAN,
                is_previous BOOLEAN,
                finished BOOLEAN,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Projections
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_projections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                player_id INTEGER,
                expected_minutes REAL,
                expected_goals REAL,
                expected_assists REAL,
                expected_clean_sheet_probability REAL,
                expected_fpl_points REAL,
                horizon_points TEXT,
                confidence REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(gameweek, player_id)
            );
            """)

            # Availability
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS player_availability (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER,
                gameweek INTEGER,
                availability_probability REAL,
                start_probability REAL,
                rotation_risk REAL,
                injury_risk REAL,
                news TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(gameweek, player_id)
            );
            """)

            # Team Snapshots
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS team_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER,
                gameweek INTEGER,
                overall_points INTEGER,
                overall_rank INTEGER,
                bank INTEGER,
                team_value INTEGER,
                free_transfers INTEGER,
                picks_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Recommendations
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                transfers_in TEXT,
                transfers_out TEXT,
                starting_xi TEXT,
                bench_order TEXT,
                captain_id INTEGER,
                vice_captain_id INTEGER,
                chip_recommendation TEXT,
                hit_count INTEGER DEFAULT 0,
                hit_cost INTEGER DEFAULT 0,
                expected_points_hold REAL,
                expected_points_recommended REAL,
                expected_net_gain REAL,
                reasons TEXT,
                risk_assessment TEXT,
                approval_required BOOLEAN DEFAULT 0,
                approval_status TEXT DEFAULT 'PENDING',
                execution_status TEXT DEFAULT 'NOT_EXECUTED',
                transaction_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Approvals
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recommendation_id INTEGER,
                gameweek INTEGER,
                action_type TEXT,
                status TEXT, -- PENDING, APPROVED, REJECTED
                decided_by TEXT,
                decided_at TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (recommendation_id) REFERENCES recommendations(id)
            );
            """)

            # Executions
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                team_id INTEGER,
                transaction_hash TEXT UNIQUE,
                mode TEXT, -- DRY_RUN or LIVE
                transfers_submitted TEXT,
                lineup_submitted TEXT,
                chip_submitted TEXT,
                response_status INTEGER,
                response_body TEXT,
                verified BOOLEAN DEFAULT 0,
                executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Chips
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS chips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER,
                name TEXT,
                status TEXT, -- AVAILABLE, USED
                gameweek_used INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # League Standings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS league_standings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                league_id INTEGER,
                league_name TEXT,
                entry_rank INTEGER,
                entry_last_rank INTEGER,
                leader_name TEXT,
                leader_points INTEGER,
                my_points INTEGER,
                points_to_leader INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Scheduler Runs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scheduler_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                stage TEXT, -- initial, refresh, primary, final_audit, safety_check
                status TEXT, -- STARTED, SUCCESS, FAILED
                details TEXT,
                run_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Audit Logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT,
                details TEXT,
                result TEXT
            );
            """)

            # Backtesting
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gameweek INTEGER,
                projected_points REAL,
                actual_points INTEGER,
                hold_actual_points INTEGER,
                transfer_delta INTEGER,
                captain_actual_points INTEGER,
                bench_points_left INTEGER,
                captain_success BOOLEAN,
                hit_points_cost INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            conn.commit()

    def log_audit(self, gameweek: int, event_type: str, details: Any, result: str):
        with self.get_connection() as conn:
            details_str = json.dumps(details) if not isinstance(details, str) else details
            conn.execute(
                "INSERT INTO audit_logs (gameweek, event_type, details, result) VALUES (?, ?, ?, ?)",
                (gameweek, event_type, details_str, result)
            )
            conn.commit()

    def save_snapshot(self, team_id: int, gameweek: int, snapshot: Dict[str, Any]):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO team_snapshots (team_id, gameweek, overall_points, overall_rank, bank, team_value, free_transfers, picks_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                team_id,
                gameweek,
                snapshot.get("overall_points"),
                snapshot.get("overall_rank"),
                snapshot.get("bank"),
                snapshot.get("team_value"),
                snapshot.get("free_transfers"),
                json.dumps(snapshot.get("picks", []))
            ))
            conn.commit()

    def save_recommendation(self, rec: Dict[str, Any]) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO recommendations (
                gameweek, transfers_in, transfers_out, starting_xi, bench_order,
                captain_id, vice_captain_id, chip_recommendation, hit_count, hit_cost,
                expected_points_hold, expected_points_recommended, expected_net_gain,
                reasons, risk_assessment, approval_required, approval_status, execution_status,
                transaction_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rec.get("gameweek"),
                json.dumps(rec.get("transfers_in", [])),
                json.dumps(rec.get("transfers_out", [])),
                json.dumps(rec.get("starting_xi", [])),
                json.dumps(rec.get("bench_order", [])),
                rec.get("captain_id"),
                rec.get("vice_captain_id"),
                rec.get("chip_recommendation"),
                rec.get("hit_count", 0),
                rec.get("hit_cost", 0),
                rec.get("expected_points_hold", 0.0),
                rec.get("expected_points_recommended", 0.0),
                rec.get("expected_net_gain", 0.0),
                json.dumps(rec.get("reasons", [])),
                rec.get("risk_assessment", ""),
                rec.get("approval_required", False),
                rec.get("approval_status", "PENDING"),
                rec.get("execution_status", "NOT_EXECUTED"),
                rec.get("transaction_hash")
            ))
            rec_id = cursor.lastrowid
            conn.commit()
            return rec_id

    def get_latest_recommendation(self, gameweek: Optional[int] = None) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if gameweek:
                cursor.execute("SELECT * FROM recommendations WHERE gameweek = ? ORDER BY id DESC LIMIT 1", (gameweek,))
            else:
                cursor.execute("SELECT * FROM recommendations ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)
            res["transfers_in"] = json.loads(res["transfers_in"] or "[]")
            res["transfers_out"] = json.loads(res["transfers_out"] or "[]")
            res["starting_xi"] = json.loads(res["starting_xi"] or "[]")
            res["bench_order"] = json.loads(res["bench_order"] or "[]")
            res["reasons"] = json.loads(res["reasons"] or "[]")
            return res

    def update_recommendation_status(self, rec_id: int, approval_status: str, execution_status: Optional[str] = None):
        with self.get_connection() as conn:
            if execution_status:
                conn.execute(
                    "UPDATE recommendations SET approval_status = ?, execution_status = ? WHERE id = ?",
                    (approval_status, execution_status, rec_id)
                )
            else:
                conn.execute(
                    "UPDATE recommendations SET approval_status = ? WHERE id = ?",
                    (approval_status, rec_id)
                )
            conn.commit()

    def get_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def record_execution(self, exec_data: Dict[str, Any]):
        with self.get_connection() as conn:
            conn.execute("""
            INSERT INTO executions (gameweek, team_id, transaction_hash, mode, transfers_submitted, lineup_submitted, chip_submitted, response_status, response_body, verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exec_data.get("gameweek"),
                exec_data.get("team_id"),
                exec_data.get("transaction_hash"),
                exec_data.get("mode"),
                json.dumps(exec_data.get("transfers_submitted", [])),
                json.dumps(exec_data.get("lineup_submitted", {})),
                exec_data.get("chip_submitted"),
                exec_data.get("response_status"),
                exec_data.get("response_body"),
                exec_data.get("verified", False)
            ))
            conn.commit()

    def has_executed_hash(self, transaction_hash: str) -> bool:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM executions WHERE transaction_hash = ?", (transaction_hash,))
            return cursor.fetchone() is not None


db = Database()
