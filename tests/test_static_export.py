"""
Unit and integration tests for static site export.
"""

import json
from pathlib import Path
import pytest
from fpl_bot.services.static_export import export_static_site
from fpl_bot.cli import run_export
from fpl_bot.core.config import settings


def test_export_static_site_creates_all_artifacts(tmp_path):
    out_dir = tmp_path / "dist"
    res = export_static_site(output_dir=str(out_dir))

    assert (out_dir / "index.html").exists()
    assert (out_dir / ".nojekyll").exists()
    assert (out_dir / "data" / "diagnostic.json").exists()
    assert (out_dir / "data" / "recommendation.json").exists()
    assert (out_dir / "data" / "audits.json").exists()
    assert (out_dir / "data" / "backtests.json").exists()
    assert res.get("version") == settings.version

    with open(out_dir / "data" / "diagnostic.json", "r", encoding="utf-8") as f:
        diag = json.load(f)
        assert "team_id" in diag
        assert diag["team_name"] == "Overspent FC"
        assert diag.get("version") == settings.version

    with open(out_dir / "data" / "recommendation.json", "r", encoding="utf-8") as f:
        rec = json.load(f)
        assert "recommended_team" in rec
        assert "starting_xi" in rec["recommended_team"]
        assert rec.get("version") == settings.version

    with open(out_dir / "index.html", "r", encoding="utf-8") as f:
        html = f.read()
        assert "Overspent FC Optimizer" in html
        assert "apiFetch" in html


def test_cli_runners(tmp_path):
    out_dir = tmp_path / "cli_dist"
    run_export(output_dir=str(out_dir))
    assert (out_dir / "index.html").exists()
