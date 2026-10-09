"""
Leak-free backtesting.

Every gameweek the bot plays only on predictions from a model fitted on earlier gameweeks (features are
point-in-time, see ``features.py``). The simulated team starts from a fresh £100m squad at the first
gameweek and then manages free transfers, hits, captaincy and autosubs exactly as the live optimizer
would, scored against the real outcomes. Section 21 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.models import BacktestResult
from fpl_bot.core.model import prediction_metrics
from fpl_bot.core.simulation import SeasonResult, simulate_season, walk_forward_predictions
from fpl_bot.data.history import load_past_seasons, season_index
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient

BASELINES = {"heuristic": "heuristic_xp", "form": "pts_avg_5"}


class BacktestingEngine:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api

    # ---- core -------------------------------------------------------------------------------
    def simulate(
        self, feats: pd.DataFrame, season_idx: int, up_to_gw: Optional[int] = None, retrain_every: int = 3
    ) -> Dict[str, Any]:
        """Runs the model-driven bot and the baselines over one season of ``feats``."""
        feats = feats.copy()
        feats["model_xp"] = walk_forward_predictions(feats, season_idx, retrain_every=retrain_every)
        model_run = simulate_season(feats, "model_xp", season_idx, end_round=up_to_gw)
        baselines = {
            name: simulate_season(feats, col, season_idx, end_round=up_to_gw) for name, col in BASELINES.items()
        }
        rows = feats[(feats["season_idx"] == season_idx) & feats["played"] & feats["model_xp"].notna()]
        if up_to_gw is not None:
            rows = rows[rows["round"] <= up_to_gw]
        quality = {"model": prediction_metrics(rows["total_points"], rows["model_xp"])}
        for name, col in BASELINES.items():
            quality[name] = prediction_metrics(rows["total_points"], rows[col].fillna(0.0))
        return {"model": model_run, "baselines": baselines, "prediction_quality": quality}

    def run_past_season(self, season: str = "2025-26", up_to_gw: Optional[int] = None) -> Dict[str, Any]:
        """Validation on a completed vaastav season; needs no FPL API access."""
        from fpl_bot.core.features import build_features
        feats = build_features(load_past_seasons())
        return self.simulate(feats, season_index(season), up_to_gw)

    # ---- live season (feeds the dashboard) -----------------------------------------------------
    def _manager_points(self, team_id: int) -> Dict[int, int]:
        try:
            hist = self.api.get_entry_history(team_id).get("current", [])
            return {h["event"]: h["points"] - h.get("event_transfers_cost", 0) for h in hist}
        except Exception:
            return {}

    def get_latest_completed_gameweek(self) -> int:
        try:
            events = self.api.get_bootstrap_static().get("events", [])
            finished = [e["id"] for e in events if e.get("finished")]
            return max(finished) if finished else 1
        except Exception:
            return 1

    def run_all_historical(self, up_to_gw: Optional[int] = None) -> List[BacktestResult]:
        """Simulates the current season so far and stores one ``backtest_runs`` row per gameweek."""
        from fpl_bot.services.forecast_service import forecast_service
        if up_to_gw is None:
            up_to_gw = self.get_latest_completed_gameweek()
        season = season_index(settings.season)
        out = self.simulate(forecast_service.feature_frame(), season, up_to_gw, retrain_every=2)
        run: SeasonResult = out["model"]
        manager = self._manager_points(settings.team_id)

        results = []
        for _, r in run.rounds.iterrows():
            gw = int(r["round"])
            actual_mgr = manager.get(gw, 0)
            delta = int(round(r["points"])) - actual_mgr if gw in manager else 0
            results.append(BacktestResult(
                gameweek=gw,
                projected_points=round(float(r["predicted"]), 1),
                actual_points=int(round(r["points"])),
                hold_actual_points=int(actual_mgr),
                transfer_delta=delta,
                captain_actual_points=int(r["captain_points"]),
                vice_captain_actual_points=int(r["vice_points"]),
                bench_points_left=int(r["bench_points"]),
                captain_success=bool(r["captain_best"]),  # captain top-scored in the XI
                hit_points_cost=int(r["hits"]) * 4,
                hit_points_gain=0,
                notes=(
                    f"Walk-forward model team scored {r['points']:.0f} pts (captain {r['captain']}); "
                    f"manager scored {actual_mgr} pts." if gw in manager else
                    f"Walk-forward model team scored {r['points']:.0f} pts (captain {r['captain']})."
                ),
            ))
        with db.get_connection() as conn:
            for res in results:
                conn.execute("""
                INSERT INTO backtest_runs (
                    gameweek, projected_points, actual_points, hold_actual_points,
                    transfer_delta, captain_actual_points, bench_points_left,
                    captain_success, hit_points_cost, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    res.gameweek, res.projected_points, res.actual_points, res.hold_actual_points,
                    res.transfer_delta, res.captain_actual_points, res.bench_points_left,
                    res.captain_success, res.hit_points_cost, res.notes,
                ))
            conn.commit()
        return results


backtesting_engine = BacktestingEngine()
