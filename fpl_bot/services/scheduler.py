"""
Dynamic deadline scheduler using APScheduler and live FPL deadlines.
Section 15 of FPL-Optimizer.md.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional
import zoneinfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class DeadlineScheduler:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self.scheduler = BackgroundScheduler(timezone=zoneinfo.ZoneInfo("UTC"))
        self.target_tz = zoneinfo.ZoneInfo(settings.timezone)
        self._orchestrator_callback: Optional[Callable[[int, str], None]] = None

    def set_orchestrator_callback(self, callback: Callable[[int, str], None]):
        self._orchestrator_callback = callback

    def get_next_gameweek_info(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves next upcoming Gameweek and parses deadline time.
        """
        raw = self.api.get_bootstrap_static()
        events = raw.get("events", [])
        next_event = next((e for e in events if e.get("is_next")), None)
        if not next_event:
            # If no next event, find first unfinished
            next_event = next((e for e in events if not e.get("finished")), None)
            
        if not next_event:
            return None

        # Parse ISO deadline string: e.g. "2026-09-18T17:30:00Z"
        iso_str = next_event["deadline_time"].replace("Z", "+00:00")
        deadline_utc = datetime.fromisoformat(iso_str)
        deadline_local = deadline_utc.astimezone(self.target_tz)

        return {
            "id": next_event["id"],
            "name": next_event["name"],
            "deadline_utc": deadline_utc,
            "deadline_local": deadline_local,
            "deadline_str": deadline_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }

    def schedule_deadline_stages(self, gameweek_id: int, deadline_utc: datetime):
        """
        Schedules the 6 stages relative to deadline:
        T-24h, T-6h, T-3h (primary), T-90m, T-30m, T-15m
        """
        now_utc = datetime.now(timezone.utc)
        self.scheduler.remove_all_jobs()

        stage_offsets = settings.schedule_stages

        for stage, offset_minutes in stage_offsets.items():
            run_time = deadline_utc - timedelta(minutes=offset_minutes)
            if run_time > now_utc:
                job_id = f"gw{gameweek_id}_{stage}"
                self.scheduler.add_job(
                    func=self._execute_stage,
                    trigger=DateTrigger(run_date=run_time),
                    args=[gameweek_id, stage],
                    id=job_id,
                    name=f"GW{gameweek_id} {stage} stage",
                    replace_existing=True
                )
                local_run_time = run_time.astimezone(self.target_tz)
                db.log_audit(
                    gameweek=gameweek_id,
                    event_type="STAGE_SCHEDULED",
                    details={"stage": stage, "run_time": local_run_time.strftime("%Y-%m-%d %H:%M:%S %Z")},
                    result="SCHEDULED"
                )

    def _execute_stage(self, gameweek: int, stage: str):
        """Dispatches scheduled stage execution to Orchestrator."""
        db.log_audit(gameweek, f"STAGE_TRIGGERED_{stage.upper()}", {"stage": stage}, "RUNNING")
        if self._orchestrator_callback:
            try:
                self._orchestrator_callback(gameweek, stage)
                db.log_audit(gameweek, f"STAGE_COMPLETED_{stage.upper()}", {"stage": stage}, "SUCCESS")
            except Exception as e:
                db.log_audit(gameweek, f"STAGE_ERROR_{stage.upper()}", {"stage": stage, "error": str(e)}, "FAILED")

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
        # Schedule next gameweek automatically on start
        gw_info = self.get_next_gameweek_info()
        if gw_info:
            self.schedule_deadline_stages(gw_info["id"], gw_info["deadline_utc"])

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()

    def get_scheduled_jobs(self) -> List[Dict[str, Any]]:
        jobs = []
        for j in self.scheduler.get_jobs():
            run_time = j.next_run_time
            local_time = run_time.astimezone(self.target_tz) if run_time else None
            jobs.append({
                "id": j.id,
                "name": j.name,
                "next_run_utc": run_time.isoformat() if run_time else None,
                "next_run_local": local_time.strftime("%Y-%m-%d %H:%M:%S %Z") if local_time else None,
            })
        return jobs

    def _is_matchday_or_settlement_window(self, gameweek_id: int) -> bool:
        """
        Evaluates whether current local time is within 00:00 IST on a matchday
        or the day after a matchday (for bonus and autosubs calculation).
        """
        now_local = datetime.now(self.target_tz)
        if now_local.hour != 0:
            return False

        try:
            fixtures = self.api.get_fixtures()
            target_dates = set()
            for f in fixtures:
                if f.get("event") in (gameweek_id, max(1, gameweek_id - 1)) and f.get("kickoff_time"):
                    ko_utc = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00"))
                    ko_date = ko_utc.astimezone(self.target_tz).date()
                    target_dates.add(ko_date)
                    target_dates.add(ko_date + timedelta(days=1))
            return now_local.date() in target_dates
        except Exception:
            return False

    def check_and_run_scheduled_workflow(
        self,
        stage: str = "auto",
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluates dynamic deadline timing against approved milestones:
        1. T-3h transfer deadline milestone (150-210 mins before deadline).
        2. Matchday at 00:00 IST and next day at 00:00 IST for bonus & autosubs.
        Intermediate builds are eliminated.
        """
        from fpl_bot.agents.orchestrator import orchestrator

        gw_info = self.get_next_gameweek_info()
        if not gw_info:
            return {"status": "NO_ACTIVE_GAMEWEEK", "executed": False}

        gw_id = gw_info["id"]
        deadline_utc = gw_info["deadline_utc"]
        now_utc = datetime.now(timezone.utc)
        mins_remaining = (deadline_utc - now_utc).total_seconds() / 60.0
        hours_remaining = mins_remaining / 60.0

        active_stage = None
        # Detect active milestone if stage is auto
        if stage == "auto":
            if force:
                active_stage = "manual_trigger"
            elif mins_remaining < 0:
                active_stage = "post_deadline"
                db.log_audit(gw_id, "DEADLINE_LOCKOUT", {"mins_past": abs(mins_remaining)}, "LOCKED")
                return {
                    "gameweek": gw_id,
                    "gameweek_name": gw_info["name"],
                    "deadline_local": gw_info["deadline_str"],
                    "hours_remaining": round(hours_remaining, 2),
                    "stage": "post_deadline",
                    "executed": False,
                    "status": "DEADLINE_LOCKOUT",
                    "transaction_hash": None,
                }
            elif 150 <= mins_remaining <= 210:
                # T-3h primary transfer deadline milestone
                active_stage = "primary"
            elif self._is_matchday_or_settlement_window(gw_id):
                # 00:00 IST on matchday or day after for bonus & autosubs calculation
                active_stage = "matchday_settlement"
            else:
                # All intermediate builds eliminated: skip optimization and build
                return {
                    "gameweek": gw_id,
                    "gameweek_name": gw_info["name"],
                    "deadline_local": gw_info["deadline_str"],
                    "hours_remaining": round(hours_remaining, 2),
                    "stage": "none",
                    "executed": False,
                    "status": "SKIPPED_NO_BUILD_DUE",
                    "transaction_hash": None,
                }
        else:
            active_stage = stage

        # Execute optimization cycle
        rec = orchestrator.run_optimization_cycle(stage=active_stage)
        executed = True

        return {
            "gameweek": gw_id,
            "gameweek_name": gw_info["name"],
            "deadline_local": gw_info["deadline_str"],
            "hours_remaining": round(hours_remaining, 2),
            "stage": active_stage,
            "executed": executed,
            "transaction_hash": rec.transaction_hash if rec else None,
        }


scheduler_service = DeadlineScheduler()

