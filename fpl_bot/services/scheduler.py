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

    def check_and_run_scheduled_workflow(
        self,
        stage: str = "auto",
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluates dynamic deadline timing against configured milestones
        (T-24h, T-6h, T-3h, T-90m, T-30m, T-15m) for GitHub Actions automation.
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
            if mins_remaining < 0:
                active_stage = "post_deadline"
                db.log_audit(gw_id, "DEADLINE_LOCKOUT", {"mins_past": abs(mins_remaining)}, "LOCKED")
            elif 10 <= mins_remaining <= 20:
                active_stage = "safety_check"      # T-15m
            elif 20 < mins_remaining <= 45:
                active_stage = "final_audit"       # T-30m
            elif 75 <= mins_remaining <= 105:
                active_stage = "lineup_check"      # T-90m
            elif 165 <= mins_remaining <= 195:
                active_stage = "primary"           # T-3h (User primary run)
            elif 345 <= mins_remaining <= 375:
                active_stage = "refresh"           # T-6h
            elif 1410 <= mins_remaining <= 1470:
                active_stage = "initial"           # T-24h
            elif force:
                active_stage = "manual_trigger"
            else:
                # Routine refresh
                active_stage = "routine_refresh"
        else:
            active_stage = stage

        # Automatic post-gameweek settlement & adaptive model retraining
        prev_gw = gw_id - 1
        if prev_gw >= 1:
            latest_chk = db.get_latest_model_checkpoint()
            if not latest_chk or latest_chk.get("trained_after_gw", 0) < prev_gw:
                try:
                    from fpl_bot.services.settlement_service import settlement_service
                    from fpl_bot.services.differential_trainer import differential_trainer
                    settlement_service.settle_gameweek(prev_gw)
                    differential_trainer.train(up_to_gw=prev_gw)
                except Exception as e:
                    db.log_audit(prev_gw, "AUTO_SETTLEMENT_ERROR", {"error": str(e)}, "WARNING")

        # Execute optimization cycle if not locked out
        executed = False
        rec = None
        if active_stage != "post_deadline":
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

