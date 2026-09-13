"""
Settlement service for ingesting completed gameweek match telemetry,
computing prediction differentials (actual vs projected points), and
maintaining the historical error store for adaptive model retraining.
"""

from typing import Any, Dict, List, Optional
from fpl_bot.core.database import db
from fpl_bot.core.models import FixtureScore
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient
from fpl_bot.services.player_data import player_data_service, PlayerDataService
from fpl_bot.agents.fixture_agent import fixture_agent
from fpl_bot.agents.availability_agent import availability_agent
from fpl_bot.agents.projection_agent import projection_agent


class SettlementService:
    def __init__(self, api: Optional[FPLApiClient] = None, player_data: Optional[PlayerDataService] = None):
        self.api = api or fpl_api
        self.player_data = player_data or player_data_service

    def settle_gameweek(self, gameweek: int) -> Dict[str, Any]:
        """
        Settles a completed gameweek by evaluating actual match outcomes against
        projections, computing residuals, and populating the differential store.
        """
        # 1. Fetch live match telemetry
        live_data = self.api.get_event_live(gameweek)
        elements_live = {el["id"]: el["stats"] for el in live_data.get("elements", [])}

        players_map, teams_map, _ = self.player_data.get_all_players_and_teams()

        # 2. Retrieve or generate point-in-time projections for the gameweek
        snapshots = db.get_projection_snapshots(gameweek)
        if not snapshots:
            # Generate baseline point-in-time projections for that gameweek
            fixture_scores = fixture_agent.analyze_all_teams(list(teams_map.values()), gameweek)
            availabilities = availability_agent.evaluate_squad_availability(list(players_map.values()))
            projections = projection_agent.generate_all_projections(
                list(players_map.values()), gameweek, fixture_scores, availabilities
            )
            # Save snapshots for future reproducibility
            for pid, proj in projections.items():
                p = players_map.get(pid)
                if not p:
                    continue
                f_score = fixture_scores.get(p.team_id)
                diff = max(1.0, min(5.0, 6.0 - (f_score.fixture_score_1gw if f_score else 3.0)))
                snapshot_data = {
                    "gameweek": gameweek,
                    "player_id": pid,
                    "player_name": p.web_name,
                    "team_id": p.team_id,
                    "element_type": p.element_type,
                    "base_xp": proj.expected_fpl_points,
                    "expected_minutes": proj.expected_minutes,
                    "fixture_difficulty": diff,
                }
                db.save_projection_snapshot(snapshot_data)
                snapshots[pid] = snapshot_data

        # 3. Compute residuals and save differentials
        differentials_list = []
        total_abs_error = 0.0
        active_count = 0

        for pid, el_stats in elements_live.items():
            player = players_map.get(pid)
            if not player:
                continue

            actual_pts = el_stats.get("total_points", 0)
            actual_mins = el_stats.get("minutes", 0)

            # Snapshots projection
            proj = snapshots.get(pid, {})
            proj_pts = float(proj.get("base_xp", 0.0))
            proj_mins = float(proj.get("expected_minutes", 0.0))

            # Only track players who were either projected for minutes or played
            if actual_mins == 0 and proj_mins == 0.0 and actual_pts == 0:
                continue

            residual = round(actual_pts - proj_pts, 2)
            minutes_residual = round(actual_mins - proj_mins, 1)

            xg_val = float(el_stats.get("expected_goals", 0.0) or 0.0)
            xa_val = float(el_stats.get("expected_assists", 0.0) or 0.0)

            diff_record = {
                "gameweek": gameweek,
                "player_id": pid,
                "player_name": player.web_name,
                "team_short_name": player.team_short_name,
                "element_type": player.element_type,
                "position_name": player.position_name,
                "projected_points": proj_pts,
                "actual_points": actual_pts,
                "residual": residual,
                "projected_minutes": proj_mins,
                "actual_minutes": actual_mins,
                "minutes_residual": minutes_residual,
                "xg": xg_val,
                "xa": xa_val,
                "actual_goals": el_stats.get("goals_scored", 0),
                "actual_assists": el_stats.get("assists", 0),
                "bonus": el_stats.get("bonus", 0),
                "bps": el_stats.get("bps", 0),
            }

            db.save_gameweek_differential(diff_record)
            differentials_list.append(diff_record)

            if actual_mins > 0 or proj_mins > 30:
                total_abs_error += abs(residual)
                active_count += 1

        mae = round(total_abs_error / max(1, active_count), 2)

        # Sort by residual
        differentials_list.sort(key=lambda x: x["residual"], reverse=True)
        top_positive = differentials_list[:5]
        top_negative = differentials_list[-5:]

        summary = {
            "gameweek": gameweek,
            "settled_count": len(differentials_list),
            "active_evaluated_count": active_count,
            "mae": mae,
            "top_positive_residuals": [
                f"{d['player_name']} ({d['team_short_name']}): Actual {d['actual_points']} vs Proj {d['projected_points']} (Delta: +{d['residual']})"
                for d in top_positive
            ],
            "top_negative_residuals": [
                f"{d['player_name']} ({d['team_short_name']}): Actual {d['actual_points']} vs Proj {d['projected_points']} (Delta: {d['residual']})"
                for d in reversed(top_negative)
            ]
        }

        db.log_audit(
            gameweek=gameweek,
            event_type="GAMEWEEK_SETTLED",
            details=summary,
            result="SUCCESS"
        )
        return summary

    def backfill_historical_differentials(self, up_to_gw: int = 4) -> List[Dict[str, Any]]:
        """
        Backfills differential records across all completed historical gameweeks (GW1 to up_to_gw).
        """
        results = []
        for gw in range(1, up_to_gw + 1):
            res = self.settle_gameweek(gw)
            results.append(res)
        return results


settlement_service = SettlementService()
