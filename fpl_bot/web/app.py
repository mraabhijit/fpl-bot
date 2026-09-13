"""
FastAPI web server providing REST endpoints and modern approval dashboard.
"""

from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.services.fpl_auth import auth_service
from fpl_bot.agents.orchestrator import orchestrator
from fpl_bot.core.backtest import backtesting_engine
from fpl_bot.services.scheduler import scheduler_service

app = FastAPI(title="Autonomous FPL Optimizer", version="1.0.0")

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"


class ApprovalRequest(BaseModel):
    recommendation_id: int
    decision: str  # "APPROVE" or "REJECT"
    notes: Optional[str] = None


class TokenUpdateRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None


@app.get("/api/diagnostic")
async def get_diagnostic():
    try:
        diag = orchestrator.run_diagnostic()
        return JSONResponse(diag)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/recommendation")
async def get_latest_recommendation():
    rec = db.get_latest_recommendation()
    if not rec:
        # Run one on the fly if none exists
        rec_obj = orchestrator.run_optimization_cycle()
        rec = db.get_latest_recommendation(rec_obj.gameweek)
    return JSONResponse(rec or {})


@app.post("/api/recommendation/run")
async def trigger_optimization_run():
    try:
        rec = orchestrator.run_optimization_cycle(stage="manual_trigger")
        return JSONResponse(rec.model_dump())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/approval")
async def submit_approval(req: ApprovalRequest):
    rec = db.get_latest_recommendation()
    if not rec or rec.get("id") != req.recommendation_id:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    new_status = "APPROVED" if req.decision.upper() == "APPROVE" else "REJECTED"
    db.update_recommendation_status(req.recommendation_id, approval_status=new_status)
    db.log_audit(
        gameweek=rec.get("gameweek", 0),
        event_type="USER_APPROVAL_DECISION",
        details={"recommendation_id": req.recommendation_id, "decision": new_status, "notes": req.notes},
        result=new_status
    )
    return JSONResponse({"status": "success", "approval_status": new_status})


@app.get("/api/audits")
async def get_audits(limit: int = 50):
    logs = db.get_audit_logs(limit)
    return JSONResponse(logs)


@app.get("/api/backtests")
async def get_backtests():
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM backtest_runs ORDER BY gameweek ASC")
        rows = [dict(r) for r in cursor.fetchall()]
        return JSONResponse(rows)


@app.post("/api/backtests/run")
async def run_backtests():
    try:
        results = backtesting_engine.run_all_historical(up_to_gw=4)
        return JSONResponse([r.model_dump() for r in results])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/token")
async def update_auth_token(req: TokenUpdateRequest):
    valid = auth_service.login_with_token(req.access_token, req.refresh_token)
    return JSONResponse({
        "status": "success" if valid else "token_stored_validation_failed",
        "is_authenticated": valid
    })


@app.get("/api/scheduler/jobs")
async def get_scheduler_jobs():
    return JSONResponse(scheduler_service.get_scheduled_jobs())


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = TEMPLATES_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>FPL Optimizer Dashboard Initializing...</h1>")
