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


scheduler_service = DeadlineScheduler()
