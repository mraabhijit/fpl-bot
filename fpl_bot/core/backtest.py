"""
Backtesting engine evaluating historical Gameweeks without future data leakage.
Section 21 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional
from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.models import BacktestResult, Player
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient
from fpl_bot.services.player_data import player_data_service
from fpl_bot.agents.optimization_agent import optimization_agent
from fpl_bot.agents.projection_agent import projection_agent
from fpl_bot.agents.fixture_agent import fixture_agent
from fpl_bot.agents.availability_agent import availability_agent


class BacktestingEngine:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self.player_data = player_data_service

    def run_backtest_for_gameweek(self, gameweek: int, team_id: Optional[int] = None) -> BacktestResult:
        """
        Simulates optimizer decision for a completed Gameweek and benchmarks vs actual outcomes.
        """
        tid = team_id or settings.team_id
        
        # 1. Fetch actual picks & live points for the gameweek
        actual_picks_data = self.api.get_entry_picks(gameweek, tid)
        actual_entry_history = actual_picks_data.get("entry_history", {})
        actual_points = actual_entry_history.get("points", 0)
        actual_bench_pts = actual_entry_history.get("points_on_bench", 0)

        # 2. Fetch live event points for all players
        live_data = self.api.get_event_live(gameweek)
        live_elements = {el["id"]: el["stats"] for el in live_data.get("elements", [])}

        players_map, teams_map, _ = self.player_data.get_all_players_and_teams()

        # 3. Simulate decision prior to deadline using point-in-time state
        # Previous squad
        prev_gw = max(1, gameweek - 1)
        prev_squad = self.player_data.get_current_squad(tid, prev_gw)

        fixture_scores = fixture_agent.analyze_all_teams(list(teams_map.values()), gameweek)
        availabilities = availability_agent.evaluate_squad_availability(list(players_map.values()))
        projections = projection_agent.generate_all_projections(
            list(players_map.values()), gameweek, fixture_scores, availabilities
        )

        rec = optimization_agent.optimize(
            gameweek=gameweek,
            current_squad=prev_squad,
            all_players=players_map,
            projections=projections,
            availabilities=availabilities
        )

        # 4. Evaluate actual points that the recommended team would have earned (including autosubs)
        starter_mins = {pid: live_elements.get(pid, {}).get("minutes", 0) for pid in rec.starting_xi}
        starter_pts = {pid: live_elements.get(pid, {}).get("total_points", 0) for pid in rec.starting_xi}
        
        # Captaincy resolution
        cap_mins = starter_mins.get(rec.captain_id, 0)
        rec_captain_pts = starter_pts.get(rec.captain_id, 0)
        rec_vice_pts = starter_pts.get(rec.vice_captain_id, 0)
        
        effective_captain_bonus = rec_captain_pts if cap_mins > 0 else (rec_vice_pts if starter_mins.get(rec.vice_captain_id, 0) > 0 else 0)

        # Goalkeeper substitution
        starting_gk = next(pid for pid in rec.starting_xi if players_map[pid].element_type == 1)
        bench_gk = rec.bench_order[0]
        actual_gk_pts = starter_pts[starting_gk]
        if starter_mins[starting_gk] == 0 and live_elements.get(bench_gk, {}).get("minutes", 0) > 0:
            actual_gk_pts = live_elements.get(bench_gk, {}).get("total_points", 0)

        # Outfield substitutions
        outfield_starters = [pid for pid in rec.starting_xi if players_map[pid].element_type != 1]
        active_counts = {
            2: sum(1 for pid in outfield_starters if starter_mins[pid] > 0 and players_map[pid].element_type == 2),
            3: sum(1 for pid in outfield_starters if starter_mins[pid] > 0 and players_map[pid].element_type == 3),
            4: sum(1 for pid in outfield_starters if starter_mins[pid] > 0 and players_map[pid].element_type == 4),
        }
        
        missing_outfield_count = sum(1 for pid in outfield_starters if starter_mins[pid] == 0)
        bench_outfield = rec.bench_order[1:]  # [sub1, sub2, sub3]
        autosub_pts = 0
        
        if missing_outfield_count > 0:
            slots_to_fill = missing_outfield_count
            for s_idx, sub_id in enumerate(bench_outfield):
                if slots_to_fill <= 0:
                    break
                sub_min = live_elements.get(sub_id, {}).get("minutes", 0)
                if sub_min > 0:
                    sub_pos = players_map[sub_id].element_type
                    d_new = active_counts[2] + (1 if sub_pos == 2 else 0)
                    m_new = active_counts[3] + (1 if sub_pos == 3 else 0)
                    f_new = active_counts[4] + (1 if sub_pos == 4 else 0)
                    
                    if d_new <= 5 and m_new <= 5 and f_new <= 3:
                        rem_bench_pos = [players_map[b].element_type for b in bench_outfield[s_idx+1:]]
                        avail_d = sum(1 for p in rem_bench_pos if p == 2)
                        avail_m = sum(1 for p in rem_bench_pos if p == 3)
                        avail_f = sum(1 for p in rem_bench_pos if p == 4)
                        if (d_new + avail_d >= 3) and (m_new + avail_m >= 2) and (f_new + avail_f >= 1):
                            # Sub comes on!
                            autosub_pts += live_elements.get(sub_id, {}).get("total_points", 0)
                            active_counts[sub_pos] += 1
                            slots_to_fill -= 1

        outfield_pts = sum(starter_pts[pid] for pid in outfield_starters if starter_mins[pid] > 0)
        rec_actual_total_pts = actual_gk_pts + outfield_pts + autosub_pts + effective_captain_bonus

        # Actual captain points
        actual_captain_pick = next((p for p in actual_picks_data.get("picks", []) if p.get("is_captain")), None)
        actual_captain_id = actual_captain_pick["element"] if actual_captain_pick else None
        actual_cap_pts = live_elements.get(actual_captain_id, {}).get("total_points", 0) if actual_captain_id else 0

        captain_success = (rec_captain_pts >= actual_cap_pts)
        transfer_delta = int(rec_actual_total_pts - actual_points)

        result = BacktestResult(
            gameweek=gameweek,
            projected_points=rec.expected_points_recommended,
            actual_points=int(rec_actual_total_pts),
            hold_actual_points=actual_points,
            transfer_delta=transfer_delta,
            captain_actual_points=rec_captain_pts,
            vice_captain_actual_points=rec_vice_pts,
            bench_points_left=actual_bench_pts,
            captain_success=captain_success,
            hit_points_cost=rec.hit_cost,
            hit_points_gain=max(0, transfer_delta),
            notes=f"Optimized squad scored {rec_actual_total_pts} pts vs actual {actual_points} pts (Delta: {transfer_delta:+d} pts)"
        )

        # Save to SQLite
        with db.get_connection() as conn:
            conn.execute("""
            INSERT INTO backtest_runs (
                gameweek, projected_points, actual_points, hold_actual_points,
                transfer_delta, captain_actual_points, bench_points_left,
                captain_success, hit_points_cost, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result.gameweek,
                result.projected_points,
                result.actual_points,
                result.hold_actual_points,
                result.transfer_delta,
                result.captain_actual_points,
                result.bench_points_left,
                result.captain_success,
                result.hit_points_cost,
                result.notes
            ))
            conn.commit()

        return result

    def run_all_historical(self, up_to_gw: int = 4) -> List[BacktestResult]:
        results = []
        for gw in range(2, up_to_gw + 1):
            try:
                res = self.run_backtest_for_gameweek(gw)
                results.append(res)
            except Exception as e:
                db.log_audit(gw, "BACKTEST_ERROR", {"error": str(e)}, "FAILED")
        return results


backtesting_engine = BacktestingEngine()
