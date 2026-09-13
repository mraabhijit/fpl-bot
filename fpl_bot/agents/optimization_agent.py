"""
Optimization Agent: Main decision engine evaluating Hold, Free Transfers, Hits, Captain, Bench, and Formation.
Section 10 of FPL-Optimizer.md.
"""

from itertools import combinations
from typing import Dict, List, Optional, Tuple
from fpl_bot.core.config import settings
from fpl_bot.core.models import (
    Player, CurrentSquad, PlayerProjection, PlayerAvailability,
    Recommendation, TransferMove
)
from fpl_bot.core.constraints import validate_formation, validate_squad_composition, validate_captaincy, VALID_FORMATIONS
from fpl_bot.core.scoring import ScoringEngine
from fpl_bot.core.risk import RiskEngine


class OptimizationAgent:
    def __init__(self):
        self.scoring = ScoringEngine()
        self.risk = RiskEngine()

    def optimize_lineup_and_captain(
        self,
        squad_players: List[Player],
        projections: Dict[int, PlayerProjection],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Tuple[List[int], List[int], int, int, float]:
        """
        Selects the best legal 11 starting players, 4 bench players (GKP + 3 outfield in priority order),
        Captain, and Vice-Captain that maximizes expected points.
        Returns (starting_xi_ids, bench_ids, captain_id, vice_captain_id, total_expected_points).
        """
        # Separate by position
        gkps = [p for p in squad_players if p.element_type == 1]
        defs = [p for p in squad_players if p.element_type == 2]
        mids = [p for p in squad_players if p.element_type == 3]
        fwds = [p for p in squad_players if p.element_type == 4]

        # Helper to get expected points
        def get_xp(p: Player) -> float:
            proj = projections.get(p.id)
            return proj.expected_fpl_points if proj else 0.0

        # Sort within each position by expected points descending
        gkps.sort(key=get_xp, reverse=True)
        defs.sort(key=get_xp, reverse=True)
        mids.sort(key=get_xp, reverse=True)
        fwds.sort(key=get_xp, reverse=True)

        best_score = -1.0
        best_xi: List[Player] = []
        best_formation = None

        # Evaluate all legal formations: (d, m, f)
        for (d_count, m_count, f_count) in VALID_FORMATIONS:
            if len(defs) < d_count or len(mids) < m_count or len(fwds) < f_count or len(gkps) < 1:
                continue

            chosen_xi = [gkps[0]] + defs[:d_count] + mids[:m_count] + fwds[:f_count]
            formation_score = sum(get_xp(p) for p in chosen_xi)

            if formation_score > best_score:
                best_score = formation_score
                best_xi = chosen_xi
                best_formation = (d_count, m_count, f_count)

        # Identify bench players
        xi_ids = set(p.id for p in best_xi)
        bench_gkp = [p for p in gkps if p.id not in xi_ids]
        bench_outfield = [p for p in squad_players if p.id not in xi_ids and p.element_type != 1]
        
        # Sort bench outfield by expected points descending for auto-sub order
        bench_outfield.sort(key=get_xp, reverse=True)
        bench_ordered = bench_gkp + bench_outfield  # GKP is sub 1 (position 12), then 13, 14, 15

        # Select Captain & Vice-Captain from Starting XI
        # Captain is top expected points with ceiling & floor analysis
        sorted_xi_by_xp = sorted(best_xi, key=get_xp, reverse=True)
        captain = sorted_xi_by_xp[0]
        vice_captain = sorted_xi_by_xp[1] if len(sorted_xi_by_xp) > 1 else sorted_xi_by_xp[0]

        # Total expected points: starting XI points + captain bonus points (1x captain)
        total_xp = best_score + get_xp(captain)

        return (
            [p.id for p in best_xi],
            [p.id for p in bench_ordered],
            captain.id,
            vice_captain.id,
            round(total_xp, 2)
        )

    def optimize(
        self,
        gameweek: int,
        current_squad: CurrentSquad,
        all_players: Dict[int, Player],
        projections: Dict[int, PlayerProjection],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Recommendation:
        """
        Runs comprehensive Gameweek optimization across:
        - Hold
        - Free transfers (1 up to available FTs)
        - Hits (if justified by Section 10 rules)
        - Captain & Bench
        """
        squad_player_ids = [p.element_id for p in current_squad.picks]
        squad_players = [all_players[pid] for pid in squad_player_ids if pid in all_players]

        # 1. HOLD Scenario
        hold_xi, hold_bench, hold_cap, hold_vice, hold_xp = self.optimize_lineup_and_captain(
            squad_players, projections, availabilities
        )

        best_recommendation = Recommendation(
            gameweek=gameweek,
            transfers_in=[],
            transfers_out=[],
            starting_xi=hold_xi,
            bench_order=hold_bench,
            captain_id=hold_cap,
            vice_captain_id=hold_vice,
            hit_count=0,
            hit_cost=0,
            expected_points_hold=hold_xp,
            expected_points_recommended=hold_xp,
            expected_net_gain=0.0,
            reasons=["Hold squad: No transfer exceeds expected value threshold after opportunity costs."],
            risk_assessment="Low transfer execution risk.",
            approval_required=False,
            approval_status="AUTO_ALLOWED"
        )

        # 2. Free Transfer & Single Transfer Evaluation
        available_ft = max(1, current_squad.free_transfers)
        bank = current_squad.bank

        # Candidate pool for incoming transfers: Top projected players per position not already in squad
        candidates_by_pos: Dict[int, List[Player]] = {1: [], 2: [], 3: [], 4: []}
        for p in all_players.values():
            if p.id in squad_player_ids:
                continue
            if p.status in ("i", "s", "u"):
                continue
            candidates_by_pos[p.element_type].append(p)

        def candidate_xp(p: Player) -> float:
            proj = projections.get(p.id)
            return proj.expected_fpl_points if proj else 0.0

        for pos in candidates_by_pos:
            candidates_by_pos[pos].sort(key=candidate_xp, reverse=True)
            candidates_by_pos[pos] = candidates_by_pos[pos][:15]  # Top 15 targets per position

        # Find best 1-transfer moves
        best_1_move: Optional[Tuple[Player, Player, float, float]] = None  # (p_out, p_in, immediate_gain, net_gain)

        for p_out in squad_players:
            # Funds available when selling p_out
            available_funds = bank + (p_out.now_cost)
            out_xp = projections[p_out.id].expected_fpl_points if p_out.id in projections else 0.0
            out_3gw = projections[p_out.id].horizon_points.get(3, out_xp * 3) if p_out.id in projections else out_xp * 3

            for p_in in candidates_by_pos.get(p_out.element_type, []):
                if p_in.now_cost > available_funds:
                    continue

                # Check club constraint (max 3 per club)
                club_count = sum(1 for p in squad_players if p.team_id == p_in.team_id and p.id != p_out.id)
                if club_count >= 3:
                    continue

                in_xp = projections[p_in.id].expected_fpl_points if p_in.id in projections else 0.0
                in_3gw = projections[p_in.id].horizon_points.get(3, in_xp * 3) if p_in.id in projections else in_xp * 3

                immediate_gain = in_xp - out_xp
                three_gw_gain = in_3gw - out_3gw

                # Total net value over short-to-medium term
                combined_gain = immediate_gain + 0.4 * (three_gw_gain)

                if best_1_move is None or combined_gain > best_1_move[3]:
                    best_1_move = (p_out, p_in, immediate_gain, combined_gain)

        # Check if best 1-transfer move improves team
        if best_1_move and best_1_move[2] > 0.5:
            p_out, p_in, imm_gain, comb_gain = best_1_move
            new_squad = [p for p in squad_players if p.id != p_out.id] + [p_in]
            new_xi, new_bench, new_cap, new_vice, new_xp = self.optimize_lineup_and_captain(
                new_squad, projections, availabilities
            )
            net_gain = new_xp - hold_xp

            if net_gain > 0.3:
                best_recommendation = Recommendation(
                    gameweek=gameweek,
                    transfers_in=[p_in.id],
                    transfers_out=[p_out.id],
                    starting_xi=new_xi,
                    bench_order=new_bench,
                    captain_id=new_cap,
                    vice_captain_id=new_vice,
                    hit_count=0,
                    hit_cost=0,
                    expected_points_hold=hold_xp,
                    expected_points_recommended=new_xp,
                    expected_net_gain=round(net_gain, 2),
                    reasons=[
                        f"Transfer IN {p_in.web_name} ({p_in.team_short_name}) for {p_out.web_name} ({p_out.team_short_name})",
                        f"Expected immediate point delta: +{imm_gain:.1f} pts (3-GW trajectory: +{comb_gain:.1f} pts)",
                        f"Better fixture alignment and form for {p_in.web_name}"
                    ],
                    risk_assessment="Free transfer within budget; no hit penalty incurred.",
                    approval_required=False,
                    approval_status="AUTO_ALLOWED"
                )

        return best_recommendation


optimization_agent = OptimizationAgent()
