"""
Policy and execution permission engine enforcing Section 16 safety requirements.
"""

from typing import Dict, List, Optional, Tuple
from fpl_bot.core.config import settings


class ActionType:
    LINEUP_CHANGE = "LINEUP_CHANGE"
    FREE_TRANSFER = "FREE_TRANSFER"
    HIT_TRANSFER = "HIT_TRANSFER"
    CHIP_ACTIVATION = "CHIP_ACTIVATION"


class ExecutionPermissionEngine:
    @staticmethod
    def evaluate_permission(
        action_type: str,
        hit_count: int = 0,
        chip: Optional[str] = None,
        is_dry_run: bool = True,
        is_auth_valid: bool = False,
        is_deadline_passed: bool = False,
        is_duplicate_hash: bool = False,
        is_data_stale: bool = False,
        user_approved: bool = False
    ) -> Tuple[bool, str]:
        """
        Determines whether an action is permitted to execute.
        Returns (is_permitted, reason).
        """
        # Universal NEVER ALLOWED rules (Section 16)
        if is_deadline_passed:
            return False, "DENIED: Action attempted after Gameweek deadline"

        if is_duplicate_hash:
            return False, "DENIED: Duplicate transaction hash detected (already executed)"

        if is_data_stale:
            return False, "DENIED: Squad or API data is stale"

        if not is_dry_run and not is_auth_valid:
            return False, "DENIED: Live execution requires verified authentication"

        # In DRY_RUN mode, simulate actions safely
        if is_dry_run:
            if action_type in (ActionType.HIT_TRANSFER, ActionType.CHIP_ACTIVATION):
                if not user_approved:
                    return False, f"APPROVAL_REQUIRED: {action_type} requires explicit user approval before dry-run completion"
            return True, "ALLOWED: Dry run simulation permitted"

        # LIVE Execution Policy
        if action_type == ActionType.CHIP_ACTIVATION or chip is not None:
            if not user_approved:
                return False, f"APPROVAL_REQUIRED: Chip activation '{chip}' requires explicit user confirmation"
            return True, f"ALLOWED: Chip '{chip}' approved by user"

        if action_type == ActionType.HIT_TRANSFER or hit_count > 0:
            if not user_approved:
                return False, f"APPROVAL_REQUIRED: Hit transfer ({hit_count} extra transfers, -{hit_count*4} pts) requires explicit user confirmation"
            return True, f"ALLOWED: Hit transfer ({hit_count} extra) approved by user"

        if action_type in (ActionType.LINEUP_CHANGE, ActionType.FREE_TRANSFER):
            # Routine actions automatically allowed if budget & rules satisfied
            return True, "ALLOWED: Routine management action automatically allowed"

        return False, f"DENIED: Unknown action type {action_type}"
