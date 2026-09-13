"""
Static site exporter for GitHub Pages hosting.
Section 17 and Section 27 of FPL-Optimizer.md.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from fpl_bot.agents.orchestrator import orchestrator
from fpl_bot.core.config import settings
from fpl_bot.core.database import db


def export_static_site(output_dir: str = "dist") -> Dict[str, Any]:
    """
    Exports the complete optimizer dashboard, live recommendation,
    diagnostic telemetry, audit logs, and backtests into a static bundle
    ready for deployment to GitHub Pages.
    """
    out_path = Path(output_dir)
    data_path = out_path / "data"
    data_path.mkdir(parents=True, exist_ok=True)

    # 1. Export Diagnostic Telemetry
    diag = orchestrator.run_diagnostic()
    diag_file = data_path / "diagnostic.json"
    with open(diag_file, "w", encoding="utf-8") as f:
        json.dump(diag, f, indent=2)

    # 2. Export Latest Recommendation with Full Player Enrichment
    rec = db.get_latest_recommendation()
    if not rec:
        rec_obj = orchestrator.run_optimization_cycle(stage="static_export_init")
        rec = db.get_latest_recommendation(rec_obj.gameweek)
    if rec:
        enriched = orchestrator.get_enriched_teams_data(rec)
        rec.update(enriched)
    rec_file = data_path / "recommendation.json"
    with open(rec_file, "w", encoding="utf-8") as f:
        json.dump(rec or {}, f, indent=2)

    # 3. Export Audit Trail
    audits = db.get_audit_logs(limit=50)
    audits_file = data_path / "audits.json"
    with open(audits_file, "w", encoding="utf-8") as f:
        json.dump(audits, f, indent=2)

    # 4. Export Backtesting Engine Records
    backtests = db.get_backtests()
    backtests_file = data_path / "backtests.json"
    with open(backtests_file, "w", encoding="utf-8") as f:
        json.dump(backtests, f, indent=2)

    # 5. Export index.html template
    template_src = Path(__file__).resolve().parent.parent / "web" / "templates" / "index.html"
    index_dest = out_path / "index.html"
    shutil.copyfile(template_src, index_dest)

    # 6. Add .nojekyll to prevent GitHub Pages from running Jekyll transformations
    nojekyll_dest = out_path / ".nojekyll"
    nojekyll_dest.touch()

    return {
        "output_dir": str(out_path),
        "index_html": str(index_dest),
        "diagnostic_json": str(diag_file),
        "recommendation_json": str(rec_file),
        "audits_json": str(audits_file),
        "backtests_json": str(backtests_file),
    }
