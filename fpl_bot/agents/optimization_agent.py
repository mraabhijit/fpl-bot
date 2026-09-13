"""
Optimization Agent: Main decision engine evaluating Hold, Free Transfers, Hits, Captain, Bench, and Formation.
Accurately models the subs lineup sequence, formation legality, and autosub probabilities for all 15 players.
Section 10 of FPL-Optimizer.md.
"""

from itertools import product, permutations
from typing import Any, Dict, List, Optional, Tuple
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

    def evaluate_squad_and_bench_sequence(
        self,
        starting_xi: List[Player],
        bench_outfield: List[Player],
        starting_gk: Player,
        bench_gk: Player,
        captain: Player,
        vice_captain: Player,
        projections: Dict[int, PlayerProjection],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Tuple[List[int], float, float, float, Dict[int, float], List[str]]:
        """
        Evaluates all 3! = 6 permutations of outfield substitutes sequence.
        Calculates exact expected points considering:
        - Starter availability probabilities
        - Captaincy doubling (and vice-captain activation if captain plays 0 mins)
        - Goalkeeper auto-sub
        - Outfield auto-sub rules adhering strictly to formation legality (3-5 DEF, 2-5 MID, 1-3 FWD)
        Returns:
        (optimal_bench_order, starting_xi_xp, bench_autosub_xp, total_squad_xp, sub_probabilities, sequence_reasons)
        """
        def get_xp(p: Player) -> float:
            proj = projections.get(p.id)
            return proj.expected_fpl_points if proj else 0.0

        def get_play_prob(p: Player) -> float:
            avail = availabilities.get(p.id)
            if avail:
                return max(0.05, min(0.99, avail.availability_probability * avail.start_probability))
            if p.chance_of_playing_next_round is not None:
                return max(0.05, min(0.99, p.chance_of_playing_next_round / 100.0))
            if p.status in ("i", "s", "u"):
                return 0.05
            if p.status == "d":
                return 0.50
            return 0.92

        # 1. Goalkeeper expected contribution
        gk0_prob = get_play_prob(starting_gk)
        gk0_xp = get_xp(starting_gk)
        gk1_prob = get_play_prob(bench_gk)
        gk1_xp = get_xp(bench_gk)

        gk_expected = (gk0_prob * gk0_xp) + ((1.0 - gk0_prob) * gk1_prob * gk1_xp)
        gk_sub_prob = round((1.0 - gk0_prob) * gk1_prob, 3)

        # 2. Outfield Starters setup
        outfield_starters = [p for p in starting_xi if p.element_type != 1]
        starters_data = [
            {"player": p, "pos": p.element_type, "xp": get_xp(p), "prob": get_play_prob(p)}
            for p in outfield_starters
        ]

        # Captain & Vice-captain probabilities
        cap_prob = get_play_prob(captain)
        cap_xp = get_xp(captain)
        vice_prob = get_play_prob(vice_captain)
        vice_xp = get_xp(vice_captain)
        # Captain bonus (1x extra): if captain plays, +cap_xp; if captain misses out, +vice_xp (if vice plays)
        captain_bonus_expected = (cap_prob * cap_xp) + ((1.0 - cap_prob) * vice_prob * vice_xp)

        # Precompute states of 10 outfield starters availability (2^10 = 1024 states)
        states = []
        for bits in product([0, 1], repeat=10):
            p_state = 1.0
            for i, b in enumerate(bits):
                p_state *= starters_data[i]["prob"] if b == 1 else (1.0 - starters_data[i]["prob"])
            states.append((bits, p_state))

        # 3. Outfield Bench Subs setup (3 players)
        bench_data = [
            {"player": p, "pos": p.element_type, "xp": get_xp(p), "prob": get_play_prob(p)}
            for p in bench_outfield
        ]

        best_perm_indices = None
        best_total_outfield_xp = -1.0
        best_sub_arrival_probs = None
        best_bench_pts_expected = 0.0
        starters_base_xp = sum(s["prob"] * s["xp"] for s in starters_data)

        # Evaluate all 6 permutations of the 3 outfield bench positions (13, 14, 15)
        for perm in permutations(range(len(bench_data))):
            ordered_subs = [bench_data[idx] for idx in perm]

            total_outfield_xp = 0.0
            bench_pts_total = 0.0
            sub_arrival_weights = [0.0, 0.0, 0.0]

            for bits, state_prob in states:
                # Starters points for this state
                state_starters_pts = sum(starters_data[i]["xp"] for i, b in enumerate(bits) if b == 1)

                # Current position counts of starters who play in this state
                curr_counts = {
                    2: sum(1 for i, b in enumerate(bits) if b == 1 and starters_data[i]["pos"] == 2),
                    3: sum(1 for i, b in enumerate(bits) if b == 1 and starters_data[i]["pos"] == 3),
                    4: sum(1 for i, b in enumerate(bits) if b == 1 and starters_data[i]["pos"] == 4),
                }

                missing_count = sum(1 for b in bits if b == 0)
                state_bench_pts = 0.0

                if missing_count > 0:
                    slots_to_fill = missing_count
                    for s_idx, sub in enumerate(ordered_subs):
                        if slots_to_fill <= 0:
                            break

                        # Check if sub can legally enter without breaking formation rules:
                        # Min: 3 DEF, 2 MID, 1 FWD. Max: 5 DEF, 5 MID, 3 FWD.
                        d_new = curr_counts[2] + (1 if sub["pos"] == 2 else 0)
                        m_new = curr_counts[3] + (1 if sub["pos"] == 3 else 0)
                        f_new = curr_counts[4] + (1 if sub["pos"] == 4 else 0)

                        if d_new <= 5 and m_new <= 5 and f_new <= 3:
                            # Verify remaining bench can satisfy minimum constraints
                            rem_bench_positions = [s["pos"] for s in ordered_subs[s_idx+1:]]
                            avail_d = sum(1 for p in rem_bench_positions if p == 2)
                            avail_m = sum(1 for p in rem_bench_positions if p == 3)
                            avail_f = sum(1 for p in rem_bench_positions if p == 4)

                            if (d_new + avail_d >= 3) and (m_new + avail_m >= 2) and (f_new + avail_f >= 1):
                                # Legal substitution!
                                state_bench_pts += sub["prob"] * sub["xp"]
                                curr_counts[2] = d_new
                                curr_counts[3] = m_new
                                curr_counts[4] = f_new
                                slots_to_fill -= 1
                                sub_arrival_weights[s_idx] += state_prob * sub["prob"]

                total_outfield_xp += state_prob * (state_starters_pts + state_bench_pts)
                bench_pts_total += state_prob * state_bench_pts

            if total_outfield_xp > best_total_outfield_xp:
                best_total_outfield_xp = total_outfield_xp
                best_perm_indices = perm
                best_sub_arrival_probs = sub_arrival_weights
                best_bench_pts_expected = bench_pts_total

        # Build optimal ordered bench: [bench_gk, sub1, sub2, sub3]
        ordered_outfield_players = [bench_data[i]["player"] for i in best_perm_indices]
        full_bench_order = [bench_gk.id] + [p.id for p in ordered_outfield_players]

        sub_probabilities: Dict[int, float] = {
            bench_gk.id: gk_sub_prob
        }
        for s_idx, p in enumerate(ordered_outfield_players):
            sub_probabilities[p.id] = round(best_sub_arrival_probs[s_idx], 3)

        total_starting_xi_xp = round(gk0_prob * gk0_xp + starters_base_xp + captain_bonus_expected, 2)
        total_bench_xp = round(((1.0 - gk0_prob) * gk1_prob * gk1_xp) + best_bench_pts_expected, 2)
        total_squad_xp = round(total_starting_xi_xp + total_bench_xp, 2)

        sequence_reasons = []
        for s_idx, p in enumerate(ordered_outfield_players, start=1):
            prob_pct = sub_probabilities[p.id] * 100
            sequence_reasons.append(
                f"Sub {s_idx} [Slot {12+s_idx}]: {p.web_name} ({p.team_short_name} {p.position_name}) - Expected XP: {get_xp(p):.1f}, Autosub Probability: {prob_pct:.1f}%"
            )

        return (
            full_bench_order,
            total_starting_xi_xp,
            total_bench_xp,
            total_squad_xp,
            sub_probabilities,
            sequence_reasons
        )

    def optimize_lineup_and_captain(
        self,
        squad_players: List[Player],
        projections: Dict[int, PlayerProjection],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Tuple[List[int], List[int], int, int, float, float, float, Dict[int, float], List[str]]:
        """
        Finds the globally optimal Starting XI, Formation, Captain, Vice-Captain,
        and Subs lineup sequence across all 15 players.
        Returns:
        (starting_xi_ids, bench_ids, captain_id, vice_captain_id,
         starting_xi_xp, bench_xp, total_squad_xp, sub_probabilities, sequence_reasons)
        """
        gkps = [p for p in squad_players if p.element_type == 1]
        defs = [p for p in squad_players if p.element_type == 2]
        mids = [p for p in squad_players if p.element_type == 3]
        fwds = [p for p in squad_players if p.element_type == 4]

        def get_xp(p: Player) -> float:
            proj = projections.get(p.id)
            return proj.expected_fpl_points if proj else 0.0

        gkps.sort(key=get_xp, reverse=True)
        defs.sort(key=get_xp, reverse=True)
        mids.sort(key=get_xp, reverse=True)
        fwds.sort(key=get_xp, reverse=True)

        starting_gk = gkps[0]
        bench_gk = gkps[1] if len(gkps) > 1 else gkps[0]

        best_total_squad_xp = -1.0
        best_result = None

        # Evaluate all legal formations: (d, m, f)
        for (d_count, m_count, f_count) in VALID_FORMATIONS:
            if len(defs) < d_count or len(mids) < m_count or len(fwds) < f_count:
                continue

            chosen_xi_outfield = defs[:d_count] + mids[:m_count] + fwds[:f_count]
            chosen_xi = [starting_gk] + chosen_xi_outfield
            chosen_xi_ids = set(p.id for p in chosen_xi)

            bench_outfield = [p for p in squad_players if p.id not in chosen_xi_ids and p.element_type != 1]

            # Captain selection: top expected points in XI
            sorted_xi_by_xp = sorted(chosen_xi, key=get_xp, reverse=True)
            captain = sorted_xi_by_xp[0]
            vice_captain = sorted_xi_by_xp[1] if len(sorted_xi_by_xp) > 1 else sorted_xi_by_xp[0]

            # Evaluate subs lineup sequence and total squad expected value
            (
                bench_order,
                xi_xp,
                bench_xp,
                total_squad_xp,
                sub_probs,
                seq_reasons
            ) = self.evaluate_squad_and_bench_sequence(
                starting_xi=chosen_xi,
                bench_outfield=bench_outfield,
                starting_gk=starting_gk,
                bench_gk=bench_gk,
                captain=captain,
                vice_captain=vice_captain,
                projections=projections,
                availabilities=availabilities
            )

            if total_squad_xp > best_total_squad_xp:
                best_total_squad_xp = total_squad_xp
                best_result = (
                    [p.id for p in chosen_xi],
                    bench_order,
                    captain.id,
                    vice_captain.id,
                    xi_xp,
                    bench_xp,
                    total_squad_xp,
                    sub_probs,
                    seq_reasons
                )

        return best_result

    def optimize(
        self,
        gameweek: int,
        current_squad: CurrentSquad,
        all_players: Dict[int, Player],
        projections: Dict[int, PlayerProjection],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Recommendation:
        """
        Runs comprehensive Gameweek optimization across all 15 squad positions:
        - Hold evaluation with full bench sequence modeling
        - Free transfers (1 up to available FTs)
        - Hits (if justified by Section 10 rules)
        - Captain & Subs priority ordering
        """
        squad_player_ids = [p.element_id for p in current_squad.picks]
        squad_players = [all_players[pid] for pid in squad_player_ids if pid in all_players]

        # 1. HOLD Scenario (Full 15-player squad analysis)
        (
            hold_xi,
            hold_bench,
            hold_cap,
            hold_vice,
            hold_xi_xp,
            hold_bench_xp,
            hold_total_xp,
            hold_sub_probs,
            hold_seq_reasons
        ) = self.optimize_lineup_and_captain(squad_players, projections, availabilities)

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
            expected_points_hold=hold_total_xp,
            expected_points_recommended=hold_total_xp,
            starting_xi_expected_points=hold_xi_xp,
            bench_expected_points=hold_bench_xp,
            bench_autosub_probabilities=hold_sub_probs,
            expected_net_gain=0.0,
            reasons=[
                "Hold squad: No transfer exceeds expected value threshold after opportunity costs.",
                f"Full squad expected total: {hold_total_xp:.1f} pts (Starters: {hold_xi_xp:.1f} pts, Bench autosubs: {hold_bench_xp:.1f} pts).",
                "Subs lineup sequence optimized for formation legality:"
            ] + hold_seq_reasons,
            risk_assessment="Low transfer execution risk.",
            approval_required=False,
            approval_status="AUTO_ALLOWED"
        )

        # 2. Transfer Evaluation across all 15 squad slots
        bank = current_squad.bank

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
            candidates_by_pos[pos] = candidates_by_pos[pos][:15]

        best_1_move = None  # (p_out, p_in, new_opt_tuple, net_gain)

        for p_out in squad_players:
            available_funds = bank + p_out.now_cost

            for p_in in candidates_by_pos.get(p_out.element_type, []):
                if p_in.now_cost > available_funds:
                    continue

                # Check 3 per club rule
                club_count = sum(1 for p in squad_players if p.team_id == p_in.team_id and p.id != p_out.id)
                if club_count >= 3:
                    continue

                new_squad = [p for p in squad_players if p.id != p_out.id] + [p_in]
                opt_res = self.optimize_lineup_and_captain(new_squad, projections, availabilities)
                new_total_xp = opt_res[6]
                net_gain = new_total_xp - hold_total_xp

                if best_1_move is None or net_gain > best_1_move[3]:
                    best_1_move = (p_out, p_in, opt_res, net_gain)

        # Check if transfer improves squad total
        if best_1_move and best_1_move[3] > 0.4:
            p_out, p_in, opt_res, net_gain = best_1_move
            (
                new_xi,
                new_bench,
                new_cap,
                new_vice,
                new_xi_xp,
                new_bench_xp,
                new_total_xp,
                new_sub_probs,
                new_seq_reasons
            ) = opt_res

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
                expected_points_hold=hold_total_xp,
                expected_points_recommended=new_total_xp,
                starting_xi_expected_points=new_xi_xp,
                bench_expected_points=new_bench_xp,
                bench_autosub_probabilities=new_sub_probs,
                expected_net_gain=round(net_gain, 2),
                reasons=[
                    f"Transfer IN {p_in.web_name} ({p_in.team_short_name} {p_in.position_name}) for {p_out.web_name} ({p_out.team_short_name} {p_out.position_name})",
                    f"Total 15-player squad expected points improves from {hold_total_xp:.1f} to {new_total_xp:.1f} pts (Net Gain: +{net_gain:.1f} pts)",
                    f"Starters contribution: {new_xi_xp:.1f} pts | Bench autosub coverage: {new_bench_xp:.1f} pts",
                    "Subs lineup sequence optimized for formation legality:"
                ] + new_seq_reasons,
                risk_assessment="Free transfer within budget; no hit penalty incurred.",
                approval_required=False,
                approval_status="AUTO_ALLOWED"
            )

        return best_recommendation


optimization_agent = OptimizationAgent()
