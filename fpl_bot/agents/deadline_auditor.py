"""
Deadline Auditor: Final pre-execution gatekeeper enforcing all checks in Section 18 of FPL-Optimizer.md.
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.models import Player, Recommendation
from fpl_bot.core.constraints import validate_formation, validate_squad_composition, validate_captaincy
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient
from fpl_bot.services.player_data import player_data_service


class DeadlineAuditor:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api

    def audit_execution_safety(
        self,
        recommendation: Recommendation,
        is_live: bool = False
    ) -> Tuple[bool, List[str]]:
        """
        Performs all strict pre-execution checks from Section 18.
        Returns (passed, list_of_audit_reasons).
        """
        failures = []
        checks_passed = []

        # 1. Re-fetch bootstrap & verify deadline is still open
        raw = self.api.get_bootstrap_static(force_refresh=True)
        events = raw.get("events", [])
        gw_event = next((e for e in events if e.get("id") == recommendation.gameweek), None)
        if not gw_event:
            return False, [f"CRITICAL: Gameweek {recommendation.gameweek} not found in FPL events."]

        deadline_str = gw_event["deadline_time"].replace("Z", "+00:00")
        deadline_dt = datetime.fromisoformat(deadline_str)
        now_utc = datetime.now(timezone.utc)

        if now_utc >= deadline_dt:
            failures.append(f"CRITICAL: Gameweek deadline has passed ({deadline_dt.isoformat()} <= {now_utc.isoformat()}). Execution stopped.")
        else:
            checks_passed.append(f"Deadline open (time remaining: {deadline_dt - now_utc})")

        # 2. Re-fetch current squad state
        players_map, _, _ = player_data_service.get_all_players_and_teams()
        current_squad = player_data_service.get_current_squad(gameweek=recommendation.gameweek)
        current_squad_ids = set(p.element_id for p in current_squad.picks)

        # 3. Check transfer legality & budget
        for out_id in recommendation.transfers_out:
            if out_id not in current_squad_ids:
                failures.append(f"CRITICAL: Transfer OUT player {out_id} is not currently in squad.")

        for in_id in recommendation.transfers_in:
            if in_id in current_squad_ids:
                failures.append(f"CRITICAL: Transfer IN player {in_id} is already in squad.")

        # Check total budget
        out_value = sum(players_map[pid].now_cost for pid in recommendation.transfers_out if pid in players_map)
        in_cost = sum(players_map[pid].now_cost for pid in recommendation.transfers_in if pid in players_map)
        if in_cost > (out_value + current_squad.bank):
            failures.append(f"CRITICAL: Transfer exceeds budget by {(in_cost - (out_value + current_squad.bank))/10:.1f}m.")
        else:
            checks_passed.append("Transfer budget check passed")

        # 4. Check resulting squad composition & formation
        resulting_squad_ids = (current_squad_ids - set(recommendation.transfers_out)).union(set(recommendation.transfers_in))
        resulting_players = [players_map[pid] for pid in resulting_squad_ids if pid in players_map]

        squad_valid, squad_msg = validate_squad_composition(resulting_players)
        if not squad_valid:
            failures.append(f"CRITICAL: Resulting squad composition invalid: {squad_msg}")
        else:
            checks_passed.append(squad_msg)

        # 5. Check Starting XI & formation legality
        starting_players = [players_map[pid] for pid in recommendation.starting_xi if pid in players_map]
        form_valid, form_msg = validate_formation(starting_players)
        if not form_valid:
            failures.append(f"CRITICAL: Formation invalid: {form_msg}")
        else:
            checks_passed.append(form_msg)

        # 6. Check captain & vice-captain
        cap_valid, cap_msg = validate_captaincy(
            recommendation.starting_xi,
            recommendation.captain_id,
            recommendation.vice_captain_id
        )
        if not cap_valid:
            failures.append(f"CRITICAL: Captaincy invalid: {cap_msg}")
        else:
            checks_passed.append(cap_msg)

        # 7. Check idempotency hash
        if recommendation.transaction_hash and db.has_executed_hash(recommendation.transaction_hash):
            failures.append(f"CRITICAL: Idempotency check failed: Hash {recommendation.transaction_hash[:12]} already executed.")
        else:
            checks_passed.append("Idempotency check passed")

        # 8. Check authentication if LIVE mode
        if is_live:
            auth_ok, auth_msg = self.api.auth.validate_session()
            if not auth_ok:
                failures.append(f"CRITICAL: Live authentication check failed: {auth_msg}")
            else:
                checks_passed.append("Authentication check passed")

        if failures:
            db.log_audit(
                gameweek=recommendation.gameweek,
                event_type="DEADLINE_AUDIT_FAILED",
                details={"failures": failures},
                result="STOPPED"
            )
            return False, failures

        db.log_audit(
            gameweek=recommendation.gameweek,
            event_type="DEADLINE_AUDIT_PASSED",
            details={"checks": checks_passed},
            result="APPROVED"
        )
        return True, checks_passed


deadline_auditor = DeadlineAuditor()
