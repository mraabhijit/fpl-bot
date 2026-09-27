"""
Unit and integration tests for static site export and scheduled workflow triggers.
"""

import json
from pathlib import Path
import pytest
from fpl_bot.services.static_export import export_static_site
from fpl_bot.services.scheduler import scheduler_service
from fpl_bot.cli import run_export, run_scheduled


def test_export_static_site_creates_all_artifacts(tmp_path):
    out_dir = tmp_path / "dist"
    res = export_static_site(output_dir=str(out_dir))

    assert (out_dir / "index.html").exists()
    assert (out_dir / ".nojekyll").exists()
    assert (out_dir / "data" / "diagnostic.json").exists()
    assert (out_dir / "data" / "recommendation.json").exists()
    assert (out_dir / "data" / "audits.json").exists()
    assert (out_dir / "data" / "backtests.json").exists()
    assert res.get("version") == "v1.1.0"

    with open(out_dir / "data" / "diagnostic.json", "r", encoding="utf-8") as f:
        diag = json.load(f)
        assert "team_id" in diag
        assert diag["team_name"] == "Overspent FC"
        assert diag.get("version") == "v1.1.0"

    with open(out_dir / "data" / "recommendation.json", "r", encoding="utf-8") as f:
        rec = json.load(f)
        assert "recommended_team" in rec
        assert "starting_xi" in rec["recommended_team"]
        assert rec.get("version") == "v1.1.0"

    with open(out_dir / "index.html", "r", encoding="utf-8") as f:
        html = f.read()
        assert "Overspent FC Optimizer" in html
        assert "v1.1.0" in html
        assert "apiFetch" in html


def test_check_and_run_scheduled_workflow():
    result = scheduler_service.check_and_run_scheduled_workflow(stage="auto", force=True)
    assert result["executed"] is True
    assert result["gameweek"] >= 1
    assert "stage" in result
    assert "hours_remaining" in result


def test_check_and_run_scheduled_workflow_skips_outside_milestones(monkeypatch):
    # Ensure outside milestone window and not matchday
    monkeypatch.setattr(scheduler_service, "_is_matchday_or_settlement_window", lambda gw: False)
    # Monkeypatch mins_remaining to be 500 mins (neither T-3h nor negative)
    orig_get_info = scheduler_service.get_next_gameweek_info
    info = orig_get_info()
    if info:
        from datetime import datetime, timezone, timedelta
        fake_deadline = datetime.now(timezone.utc) + timedelta(minutes=500)
        info["deadline_utc"] = fake_deadline
        monkeypatch.setattr(scheduler_service, "get_next_gameweek_info", lambda: info)

    result = scheduler_service.check_and_run_scheduled_workflow(stage="auto", force=False)
    assert result["executed"] is False
    assert result["status"] == "SKIPPED_NO_BUILD_DUE"


def test_cli_runners(tmp_path):
    out_dir = tmp_path / "cli_dist"
    run_export(output_dir=str(out_dir))
    assert (out_dir / "index.html").exists()
