"""
Rank and Mini-League Agent tracking overall rank progression, mini-league rival standings, and differentials.
Section 9 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional
from fpl_bot.core.config import settings
from fpl_bot.core.models import MiniLeagueStanding
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class RankAgent:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api

    def analyze_rank_and_leagues(self, team_id: Optional[int] = None) -> Dict[str, Any]:
        tid = team_id or settings.team_id
        entry = self.api.get_entry(tid)
        history = self.api.get_entry_history(tid)

        current_history = history.get("current", [])
        latest_gw_entry = current_history[-1] if current_history else {}

        overall_rank = latest_gw_entry.get("overall_rank", entry.get("summary_overall_rank", 0))
        total_points = latest_gw_entry.get("total_points", entry.get("summary_overall_points", 0))

        # Rank movement
        prev_rank = current_history[-2].get("overall_rank") if len(current_history) >= 2 else overall_rank
        rank_change = (prev_rank - overall_rank) if prev_rank else 0

        # Mini-leagues
        classic_leagues = entry.get("leagues", {}).get("classic", [])
        standings_summary: List[MiniLeagueStanding] = []

        for lg in classic_leagues:
            # Filter out broad automated leagues or include private ones
            lg_id = lg.get("id")
            lg_name = lg.get("name", "")
            entry_rank = lg.get("entry_rank", 0)
            entry_last_rank = lg.get("entry_last_rank", 0)

            # Look up standings for competitive leagues
            leader_name = ""
            leader_points = 0
            try:
                # Cache-friendly quick fetch
                res = self.api.get_classic_league_standings(lg_id)
                standings = res.get("standings", {}).get("results", [])
                if standings:
                    leader = standings[0]
                    leader_name = f"{leader.get('entry_name')} ({leader.get('player_name')})"
                    leader_points = leader.get("total", 0)
            except Exception:
                pass

            pts_to_leader = max(0, leader_points - total_points) if leader_points else 0

            standings_summary.append(MiniLeagueStanding(
                league_id=lg_id,
                league_name=lg_name,
                entry_rank=entry_rank,
                entry_last_rank=entry_last_rank,
                leader_name=leader_name,
                leader_points=leader_points,
                my_points=total_points,
                points_to_leader=pts_to_leader,
            ))

        return {
            "overall_rank": overall_rank,
            "overall_points": total_points,
            "rank_change": rank_change,
            "percentile": latest_gw_entry.get("percentile_rank"),
            "standings": standings_summary
        }


rank_agent = RankAgent()
