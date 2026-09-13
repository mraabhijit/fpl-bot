import pytest
from fpl_bot.core.permissions import ExecutionPermissionEngine, ActionType


def test_permission_never_allowed_after_deadline():
    allowed, reason = ExecutionPermissionEngine.evaluate_permission(
        action_type=ActionType.LINEUP_CHANGE,
        is_deadline_passed=True
    )
    assert allowed is False
    assert "after Gameweek deadline" in reason


def test_permission_duplicate_hash():
    allowed, reason = ExecutionPermissionEngine.evaluate_permission(
        action_type=ActionType.FREE_TRANSFER,
        is_duplicate_hash=True
    )
    assert allowed is False
    assert "Duplicate transaction hash" in reason


def test_permission_hit_requires_approval():
    # Dry run with hit but unapproved -> needs approval
    allowed, reason = ExecutionPermissionEngine.evaluate_permission(
        action_type=ActionType.HIT_TRANSFER,
        hit_count=1,
        is_dry_run=True,
        user_approved=False
    )
    assert allowed is False
    assert "APPROVAL_REQUIRED" in reason

    # Dry run with hit approved -> allowed
    allowed, reason = ExecutionPermissionEngine.evaluate_permission(
        action_type=ActionType.HIT_TRANSFER,
        hit_count=1,
        is_dry_run=True,
        user_approved=True
    )
    assert allowed is True


def test_permission_chip_requires_approval():
    # Live execution with chip unapproved -> denied
    allowed, reason = ExecutionPermissionEngine.evaluate_permission(
        action_type=ActionType.CHIP_ACTIVATION,
        chip="wildcard",
        is_dry_run=False,
        is_auth_valid=True,
        user_approved=False
    )
    assert allowed is False
    assert "APPROVAL_REQUIRED" in reason
