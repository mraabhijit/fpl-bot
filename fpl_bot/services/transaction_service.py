"""
Transaction execution service with strict idempotency hashing, dry-run safety, and post-submission verification.
Section 18 & 19 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional, Tuple
import httpx
from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.constraints import compute_transaction_hash
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class TransactionService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api

    def execute_transaction(
        self,
        team_id: int,
        gameweek: int,
        transfers: List[Dict[str, int]],  # [{"element_in": x, "element_out": y, "purchase_price": p, "selling_price": s}]
        starting_xi: List[int],  # list of element IDs
        bench_order: List[int],  # list of element IDs (12 to 15)
        captain_id: int,
        vice_captain_id: int,
        chip: Optional[str] = None,
        force_dry_run: Optional[bool] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Submits transfers and team lineup to FPL API.
        Guarded by idempotency hash check and dry-run flag.
        """
        # 1. Compute Idempotency Hash
        tx_hash = compute_transaction_hash(
            team_id=team_id,
            gameweek=gameweek,
            transfers=transfers,
            starting_xi=starting_xi,
            bench_order=bench_order,
            captain_id=captain_id,
            vice_captain_id=vice_captain_id,
            chip=chip
        )

        # 2. Check if hash has already been executed
        if db.has_executed_hash(tx_hash):
            return False, f"Transaction aborted: Duplicate hash {tx_hash[:12]} already executed.", {"hash": tx_hash}

        is_dry_run = force_dry_run if force_dry_run is not None else (settings.execution_mode == "DRY_RUN")

        # 3. Dry-Run Execution Mode
        if is_dry_run:
            exec_record = {
                "gameweek": gameweek,
                "team_id": team_id,
                "transaction_hash": tx_hash,
                "mode": "DRY_RUN",
                "transfers_submitted": transfers,
                "lineup_submitted": {
                    "starting_xi": starting_xi,
                    "bench_order": bench_order,
                    "captain": captain_id,
                    "vice_captain": vice_captain_id,
                },
                "chip_submitted": chip,
                "response_status": 200,
                "response_body": "SIMULATED_SUCCESS_DRY_RUN",
                "verified": True
            }
            db.record_execution(exec_record)
            db.log_audit(
                gameweek=gameweek,
                event_type="DRY_RUN_EXECUTION",
                details=exec_record,
                result="SUCCESS"
            )
            return True, f"Dry-run executed successfully. Hash: {tx_hash[:12]}", {"hash": tx_hash, "mode": "DRY_RUN"}

        # 4. Live Execution Mode
        # Validate authentication first
        is_auth_valid, auth_msg = self.api.auth.validate_session(team_id)
        if not is_auth_valid:
            db.log_audit(
                gameweek=gameweek,
                event_type="EXECUTION_FAILED",
                details={"reason": "Authentication failed", "msg": auth_msg},
                result="FAILED"
            )
            return False, f"Live execution denied: {auth_msg}", {"hash": tx_hash}

        headers = self.api.auth.get_auth_headers()
        headers["Content-Type"] = "application/json"

        # A. Execute Transfers if any
        if transfers:
            transfer_url = f"{settings.fpl_base_url}/transfers/"
            transfer_payload = {
                "chip": chip if chip in ("wildcard", "freehit") else None,
                "entry": team_id,
                "event": gameweek,
                "transfers": transfers,
            }
            try:
                with httpx.Client(timeout=20.0) as client:
                    t_resp = client.post(transfer_url, json=transfer_payload, headers=headers)
                    if t_resp.status_code not in (200, 201):
                        db.log_audit(gameweek, "LIVE_TRANSFER_FAILED", {"status": t_resp.status_code, "body": t_resp.text}, "FAILED")
                        return False, f"Transfers submission failed: HTTP {t_resp.status_code} - {t_resp.text[:200]}", {"hash": tx_hash}
            except Exception as e:
                db.log_audit(gameweek, "LIVE_TRANSFER_EXCEPTION", {"error": str(e)}, "FAILED")
                return False, f"Network exception during transfer submission: {str(e)}", {"hash": tx_hash}

        # B. Execute Lineup & Captaincy
        lineup_url = f"{settings.fpl_base_url}/my-team/{team_id}/"
        picks_payload: List[Dict[str, Any]] = []

        # Starting XI (positions 1 to 11)
        for idx, p_id in enumerate(starting_xi, start=1):
            picks_payload.append({
                "element": p_id,
                "position": idx,
                "is_captain": (p_id == captain_id),
                "is_vice_captain": (p_id == vice_captain_id),
            })

        # Bench (positions 12 to 15)
        for idx, p_id in enumerate(bench_order, start=12):
            picks_payload.append({
                "element": p_id,
                "position": idx,
                "is_captain": False,
                "is_vice_captain": False,
            })

        team_payload = {
            "chip": chip if chip in ("bboost", "3xc") else None,
            "picks": picks_payload,
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                l_resp = client.post(lineup_url, json=team_payload, headers=headers)
                if l_resp.status_code not in (200, 201):
                    db.log_audit(gameweek, "LIVE_LINEUP_FAILED", {"status": l_resp.status_code, "body": l_resp.text}, "FAILED")
                    return False, f"Lineup submission failed: HTTP {l_resp.status_code} - {l_resp.text[:200]}", {"hash": tx_hash}
        except Exception as e:
            db.log_audit(gameweek, "LIVE_LINEUP_EXCEPTION", {"error": str(e)}, "FAILED")
            return False, f"Network exception during lineup submission: {str(e)}", {"hash": tx_hash}

        # 5. Post-Execution Verification (Section 19)
        # Re-fetch squad to verify state change
        verified = False
        try:
            verified_data = self.api.get_my_team(team_id)
            verified_picks = verified_data.get("picks", [])
            verified_cap = next((p["element"] for p in verified_picks if p.get("is_captain")), None)
            if verified_cap == captain_id:
                verified = True
        except Exception:
            verified = False

        exec_record = {
            "gameweek": gameweek,
            "team_id": team_id,
            "transaction_hash": tx_hash,
            "mode": "LIVE",
            "transfers_submitted": transfers,
            "lineup_submitted": team_payload,
            "chip_submitted": chip,
            "response_status": 200,
            "response_body": "LIVE_SUCCESS",
            "verified": verified
        }
        db.record_execution(exec_record)
        db.log_audit(
            gameweek=gameweek,
            event_type="LIVE_EXECUTION",
            details=exec_record,
            result="SUCCESS" if verified else "UNVERIFIED"
        )

        return True, f"Live transaction executed and {'verified' if verified else 'completed'}. Hash: {tx_hash[:12]}", {"hash": tx_hash, "verified": verified}


transaction_service = TransactionService()
