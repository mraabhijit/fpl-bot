"""
Orchestrator coordinating all specialized agents, data flows, permissions, and executions.
Section 2 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional
import zoneinfo
from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.models import Recommendation, CurrentSquad
from fpl_bot.core.permissions import ExecutionPermissionEngine, ActionType
from fpl_bot.core.constraints import compute_transaction_hash
from fpl_bot.services.fpl_api import fpl_api
from fpl_bot.services.player_data import player_data_service
from fpl_bot.services.fixture_service import fixture_service
from fpl_bot.services.news_service import news_service
from fpl_bot.services.transaction_service import transaction_service
from fpl_bot.agents.projection_agent import projection_agent
from fpl_bot.agents.fixture_agent import fixture_agent
from fpl_bot.agents.availability_agent import availability_agent
from fpl_bot.agents.rank_agent import rank_agent
from fpl_bot.agents.chip_agent import chip_agent
from fpl_bot.agents.optimization_agent import optimization_agent
from fpl_bot.agents.deadline_auditor import deadline_auditor


class Orchestrator:
    def __init__(self):
        self.api = fpl_api
        self.player_data = player_data_service
        self.target_tz = zoneinfo.ZoneInfo(settings.timezone)

    def run_diagnostic(self) -> Dict[str, Any]:
        """
        Executes Section 28: First Diagnostic Run.
        Returns exact formatted structure without making any transfer.
        """
        # 1. Fetch live data
        players_map, teams_map, gameweeks = self.player_data.get_all_players_and_teams()
        curr_gw = next((gw for gw in gameweeks if gw.is_current), None)
        next_gw = next((gw for gw in gameweeks if gw.is_next), None)
        gw_num = next_gw.id if next_gw else (curr_gw.id if curr_gw else 1)
        deadline_str = next_gw.deadline_time if next_gw else "N/A"

        entry = self.api.get_entry(settings.team_id)
        history = self.api.get_entry_history(settings.team_id)
        latest_history = history.get("current", [])[-1] if history.get("current") else {}
        current_squad = self.player_data.get_current_squad(gameweek=curr_gw.id if curr_gw else 1)

        # Check authentication write access
        auth_valid, _ = self.api.auth.validate_session(settings.team_id) if self.api.auth.is_authenticated() else (False, "")

        # Separate XI and Bench
        starting_xi = [p for p in current_squad.picks if p.position <= 11]
        bench = [p for p in current_squad.picks if p.position > 11]
        captain = next((p for p in current_squad.picks if p.is_captain), None)
        vice = next((p for p in current_squad.picks if p.is_vice_captain), None)

        used_chips = [c.get("name") for c in history.get("chips", [])]
        all_chips = ["Wildcard 1", "Wildcard 2", "Free Hit 1", "Free Hit 2", "Bench Boost 1", "Bench Boost 2", "Triple Captain 1", "Triple Captain 2"]
        available_chips = [c for c in all_chips if c.lower().replace(" 1", "").replace(" 2", "") not in used_chips]

        classic_leagues = entry.get("leagues", {}).get("classic", [])

        diagnostic_data = {
            "fpl_connection": "OK",
            "team_id": settings.team_id,
            "team_name": entry.get("name", settings.team_name),
            "manager_name": f"{entry.get('player_first_name')} {entry.get('player_last_name')}",
            "current_gw": gw_num,
            "deadline": deadline_str,
            "timezone": settings.timezone,
            "overall_rank": latest_history.get("overall_rank", entry.get("summary_overall_rank", 0)),
            "overall_points": latest_history.get("total_points", entry.get("summary_overall_points", 0)),
            "team_value": f"£{current_squad.value / 10:.1f}m",
            "bank": f"£{current_squad.bank / 10:.1f}m",
            "free_transfers": current_squad.free_transfers,
            "current_xi": [
                f"{p.position}. {p.player.position_name} {p.player.web_name} ({p.player.team_short_name}) vs {p.player.next_opponent} £{p.player.now_cost/10:.1f}m"
                for p in starting_xi if p.player
            ],
            "bench": [
                f"{p.position}. {p.player.position_name} {p.player.web_name} ({p.player.team_short_name}) vs {p.player.next_opponent} £{p.player.now_cost/10:.1f}m"
                for p in bench if p.player
            ],
            "captain": f"{captain.player.web_name} ({captain.player.team_short_name})" if captain and captain.player else "N/A",
            "vice_captain": f"{vice.player.web_name} ({vice.player.team_short_name})" if vice and vice.player else "N/A",
            "available_chips": available_chips,
            "mini_leagues": [
                f"{lg.get('name')} (Rank: {lg.get('entry_rank')})" for lg in classic_leagues[:6]
            ],
            "authenticated_write_access": "YES" if auth_valid else "NO",
            "execution_mode": settings.execution_mode,
        }

        db.log_audit(
            gameweek=gw_num,
            event_type="DIAGNOSTIC_RUN",
            details=diagnostic_data,
            result="OK"
        )
        return diagnostic_data

    def run_optimization_cycle(self, stage: str = "manual") -> Recommendation:
        """
        Executes a full decision pipeline run:
        1. Fetch fresh data & snapshot
        2. Projections, Fixtures, Availability
        3. Rank & Chip evaluation
        4. Optimization (Hold vs FT vs Hit, Captain, Formation, Bench)
        5. Deadline Auditor validation
        6. Store recommendation in SQLite
        7. Execute if dry-run or auto-allowed routine action
        """
        # 1. Fetch fresh data
        players_map, teams_map, gameweeks = self.player_data.get_all_players_and_teams()
        curr_gw = next((gw for gw in gameweeks if gw.is_current), None)
        next_gw = next((gw for gw in gameweeks if gw.is_next), None)
        gw_id = next_gw.id if next_gw else (curr_gw.id + 1 if curr_gw else 1)

        current_squad = self.player_data.get_current_squad(gameweek=curr_gw.id if curr_gw else 1)

        # Snapshot
        db.save_snapshot(settings.team_id, gw_id, {
            "overall_points": current_squad.value,
            "overall_rank": 0,
            "bank": current_squad.bank,
            "team_value": current_squad.value,
            "free_transfers": current_squad.free_transfers,
            "picks": [p.model_dump() for p in current_squad.picks]
        })

        # 2. Agents
        fixture_scores = fixture_agent.analyze_all_teams(list(teams_map.values()), gw_id)
        availabilities = availability_agent.evaluate_squad_availability(list(players_map.values()))
        projections = projection_agent.generate_all_projections(
            list(players_map.values()), gw_id, fixture_scores, availabilities
        )

        # 3. Chip analysis
        history = self.api.get_entry_history(settings.team_id)
        used_chips = [c.get("name") for c in history.get("chips", [])]
        chip_rec = chip_agent.evaluate_chips(gw_id, current_squad, projections, used_chips)

        # 4. Optimization
        recommendation = optimization_agent.optimize(
            gameweek=gw_id,
            current_squad=current_squad,
            all_players=players_map,
            projections=projections,
            availabilities=availabilities
        )

        if chip_rec:
            if chip_rec.get("chip") == "wildcard" and recommendation.hit_count == 0:
                recommendation.reasons.append(
                    "Chip advisory: Hold Wildcard. Routine squad adjustment (0 hit cost) does not justify deploying an unlimited-transfers chip."
                )
            else:
                recommendation.chip_recommendation = chip_rec.get("chip")
                recommendation.reasons.append(f"Chip advisory: {chip_rec.get('reason')}")
                recommendation.approval_required = True
                recommendation.approval_status = "PENDING"
        else:
            recommendation.reasons.append(
                "Chip advisory: Hold all chips. Routine transfer management without hits optimizes expected season outcome."
            )

        if recommendation.hit_count > 0:
            recommendation.approval_required = True
            recommendation.approval_status = "PENDING"

        # Compute transaction hash
        transfers_payload = []
        for out_id, in_id in zip(recommendation.transfers_out, recommendation.transfers_in):
            transfers_payload.append({
                "element_out": out_id,
                "element_in": in_id,
                "selling_price": players_map[out_id].now_cost if out_id in players_map else 0,
                "purchase_price": players_map[in_id].now_cost if in_id in players_map else 0,
            })

        tx_hash = compute_transaction_hash(
            team_id=settings.team_id,
            gameweek=gw_id,
            transfers=transfers_payload,
            starting_xi=recommendation.starting_xi,
            bench_order=recommendation.bench_order,
            captain_id=recommendation.captain_id,
            vice_captain_id=recommendation.vice_captain_id,
            chip=recommendation.chip_recommendation
        )
        recommendation.transaction_hash = tx_hash

        # 5. Deadline Auditor Pre-check
        audit_passed, audit_msgs = deadline_auditor.audit_execution_safety(
            recommendation,
            is_live=(settings.execution_mode == "LIVE")
        )

        if not audit_passed:
            recommendation.execution_status = "FAILED"
            recommendation.execution_error = "; ".join(audit_msgs)
        else:
            # 6. Check Execution Permissions
            action_type = ActionType.FREE_TRANSFER if recommendation.transfers_in and recommendation.hit_count == 0 else (
                ActionType.HIT_TRANSFER if recommendation.hit_count > 0 else ActionType.LINEUP_CHANGE
            )
            is_auth_valid, _ = self.api.auth.validate_session() if self.api.auth.is_authenticated() else (False, "")
            
            allowed, perm_msg = ExecutionPermissionEngine.evaluate_permission(
                action_type=action_type,
                hit_count=recommendation.hit_count,
                chip=recommendation.chip_recommendation,
                is_dry_run=(settings.execution_mode == "DRY_RUN"),
                is_auth_valid=is_auth_valid,
                user_approved=(recommendation.approval_status == "APPROVED")
            )

            if allowed:
                # Execute in DRY_RUN or LIVE
                success, exec_msg, _ = transaction_service.execute_transaction(
                    team_id=settings.team_id,
                    gameweek=gw_id,
                    transfers=transfers_payload,
                    starting_xi=recommendation.starting_xi,
                    bench_order=recommendation.bench_order,
                    captain_id=recommendation.captain_id,
                    vice_captain_id=recommendation.vice_captain_id,
                    chip=recommendation.chip_recommendation
                )
                recommendation.execution_status = "DRY_RUN_OK" if settings.execution_mode == "DRY_RUN" else ("EXECUTED" if success else "FAILED")
            else:
                recommendation.execution_status = "PENDING_APPROVAL"

        # Save to database
        db.save_recommendation(recommendation.model_dump())
        return recommendation

    def get_enriched_teams_data(self, rec: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enriches a recommendation with detailed player objects, opponents, expected points,
        and current vs recommended team breakdowns for the Web UI.
        """
        gw_id = rec.get("gameweek", 5)
        players_map, teams_map, _ = self.player_data.get_all_players_and_teams()
        fixture_scores = fixture_agent.analyze_all_teams(list(teams_map.values()), gw_id)
        availabilities = availability_agent.evaluate_squad_availability(list(players_map.values()))
        projections = projection_agent.generate_all_projections(
            list(players_map.values()), gw_id, fixture_scores, availabilities
        )

        sub_probs = rec.get("bench_autosub_probabilities") or {}

        # 2. Current Team & Live match points for current squad event
        current_squad = self.player_data.get_current_squad()
        squad_gw = current_squad.event
        live_pts_map = {}
        try:
            live_data = self.api.get_event_live(squad_gw)
            for el in live_data.get("elements", []):
                live_pts_map[el["id"]] = el.get("stats", {}).get("total_points", 0)
        except Exception:
            pass

        def player_to_dict(
            pid: int,
            is_cap: bool = False,
            is_vice: bool = False,
            sub_label: Optional[str] = None,
            autosub_prob: Optional[float] = None
        ) -> Dict[str, Any]:
            p = players_map.get(pid)
            if not p:
                return {}
            proj = projections.get(pid)
            xp = proj.expected_fpl_points if proj else 0.0

            # Live actual points
            base_actual = live_pts_map.get(pid, getattr(p, "event_points", 0))
            actual_effective = base_actual * 2 if is_cap else base_actual
            sim_xp = round(xp * 2, 1) if is_cap else (round(xp * autosub_prob, 2) if autosub_prob is not None else round(xp, 1))

            return {
                "id": p.id,
                "web_name": p.web_name,
                "first_name": p.first_name,
                "second_name": p.second_name,
                "team_short_name": p.team_short_name,
                "team_name": p.team_name,
                "position_name": p.position_name,
                "element_type": p.element_type,
                "now_cost": p.now_cost,
                "now_cost_str": f"£{p.now_cost/10:.1f}m",
                "next_opponent": p.next_opponent or "BLANK",
                "expected_points": round(xp, 1),
                "predicted_points": round(xp * 2, 1) if is_cap else round(xp, 1),
                "simulated_points": sim_xp,
                "actual_points": actual_effective,
                "base_actual_points": base_actual,
                "is_captain": is_cap,
                "is_vice_captain": is_vice,
                "sub_slot_label": sub_label,
                "autosub_probability_pct": f"{autosub_prob*100:.1f}%" if autosub_prob is not None else None,
            }

        # 1. Recommended Team
        rec_xi = [
            player_to_dict(pid, is_cap=(pid == rec["captain_id"]), is_vice=(pid == rec["vice_captain_id"]))
            for pid in rec.get("starting_xi", [])
        ]
        
        bench_order = rec.get("bench_order", [])
        rec_bench = []
        if bench_order:
            # Slot 12: GK Sub
            gk_id = bench_order[0]
            gk_prob = sub_probs.get(str(gk_id), sub_probs.get(gk_id))
            rec_bench.append(player_to_dict(gk_id, sub_label="GK Sub", autosub_prob=gk_prob))

            # Slots 13, 14, 15: Outfield Subs
            for s_idx, sub_id in enumerate(bench_order[1:], start=1):
                prob = sub_probs.get(str(sub_id), sub_probs.get(sub_id))
                rec_bench.append(player_to_dict(sub_id, sub_label=f"Sub {s_idx}", autosub_prob=prob))

        d_count = sum(1 for p in rec_xi if p.get("element_type") == 2)
        m_count = sum(1 for p in rec_xi if p.get("element_type") == 3)
        f_count = sum(1 for p in rec_xi if p.get("element_type") == 4)
        rec_formation = f"{d_count}-{m_count}-{f_count}"

        # 2. Current Team
        curr_xi_picks = [p for p in current_squad.picks if p.position <= 11]
        curr_bench_picks = [p for p in current_squad.picks if p.position > 11]

        curr_xi = [
            player_to_dict(p.element_id, is_cap=p.is_captain, is_vice=p.is_vice_captain)
            for p in curr_xi_picks
        ]
        
        curr_bench_labels = ["GK Sub", "Sub 1", "Sub 2", "Sub 3"]
        curr_bench = [
            player_to_dict(p.element_id, sub_label=curr_bench_labels[idx] if idx < 4 else "Sub")
            for idx, p in enumerate(curr_bench_picks)
        ]

        curr_d = sum(1 for p in curr_xi if p.get("element_type") == 2)
        curr_m = sum(1 for p in curr_xi if p.get("element_type") == 3)
        curr_f = sum(1 for p in curr_xi if p.get("element_type") == 4)
        curr_formation = f"{curr_d}-{curr_m}-{curr_f}"
        curr_actual_total = sum(p.get("actual_points", 0) for p in curr_xi)

        return {
            "recommended_team": {
                "formation": rec_formation,
                "total_xp": rec.get("expected_points_recommended", 0.0),
                "xi_xp": rec.get("starting_xi_expected_points", 0.0),
                "bench_xp": rec.get("bench_expected_points", 0.0),
                "starting_xi": rec_xi,
                "bench": rec_bench
            },
            "current_team": {
                "formation": curr_formation,
                "gameweek": squad_gw,
                "total_xp": rec.get("expected_points_hold", 0.0),
                "actual_total_pts": curr_actual_total,
                "starting_xi": curr_xi,
                "bench": curr_bench
            },
            "transfers_in_players": [player_to_dict(pid) for pid in rec.get("transfers_in", [])],
            "transfers_out_players": [player_to_dict(pid) for pid in rec.get("transfers_out", [])],
        }


orchestrator = Orchestrator()

