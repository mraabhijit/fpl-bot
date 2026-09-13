"""
Deterministic rules, constraints, and validation for FPL squads, transfers, formations, and transactions.
"""

import hashlib
import json
from typing import Dict, List, Optional, Set, Tuple
from fpl_bot.core.models import Player, SquadPick


VALID_FORMATIONS = [
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 2, 3),
    (5, 3, 2),
    (5, 4, 1),
]


def validate_formation(starting_xi_players: List[Player]) -> Tuple[bool, str]:
    """
    Validates starting XI formation:
    - 1 GKP
    - 3-5 DEF
    - 2-5 MID
    - 1-3 FWD
    - Total 11
    """
    if len(starting_xi_players) != 11:
        return False, f"Starting XI must contain exactly 11 players (got {len(starting_xi_players)})"

    gkp = sum(1 for p in starting_xi_players if p.element_type == 1)
    defe = sum(1 for p in starting_xi_players if p.element_type == 2)
    mid = sum(1 for p in starting_xi_players if p.element_type == 3)
    fwd = sum(1 for p in starting_xi_players if p.element_type == 4)

    if gkp != 1:
        return False, f"Starting XI must have exactly 1 GKP (got {gkp})"
    if (defe, mid, fwd) not in VALID_FORMATIONS:
        return False, f"Invalid formation {defe}-{mid}-{fwd}. Must be one of {VALID_FORMATIONS}"

    return True, f"Valid formation: {defe}-{mid}-{fwd}"


def validate_squad_composition(players: List[Player]) -> Tuple[bool, str]:
    """
    Validates full 15-player squad:
    - 2 GKP, 5 DEF, 5 MID, 3 FWD
    - Max 3 players per club
    - 15 unique players
    """
    if len(players) != 15:
        return False, f"Squad must have exactly 15 players (got {len(players)})"

    player_ids = [p.id for p in players]
    if len(set(player_ids)) != 15:
        return False, "Squad contains duplicate players"

    gkp = sum(1 for p in players if p.element_type == 1)
    defe = sum(1 for p in players if p.element_type == 2)
    mid = sum(1 for p in players if p.element_type == 3)
    fwd = sum(1 for p in players if p.element_type == 4)

    if gkp != 2 or defe != 5 or mid != 5 or fwd != 3:
        return False, f"Illegal squad breakdown: {gkp} GKP, {defe} DEF, {mid} MID, {fwd} FWD"

    # Team limits
    team_counts: Dict[int, int] = {}
    for p in players:
        team_counts[p.team_id] = team_counts.get(p.team_id, 0) + 1
        if team_counts[p.team_id] > 3:
            return False, f"Exceeded limit of 3 players from team {p.team_short_name or p.team_id}"

    return True, "Squad composition valid"


def validate_captaincy(starting_xi_ids: List[int], captain_id: int, vice_captain_id: int) -> Tuple[bool, str]:
    """Ensures captain and vice-captain are distinct and both in starting XI."""
    if captain_id == vice_captain_id:
        return False, "Captain and Vice-Captain cannot be the same player"
    if captain_id not in starting_xi_ids:
        return False, f"Captain {captain_id} is not in Starting XI"
    if vice_captain_id not in starting_xi_ids:
        return False, f"Vice-Captain {vice_captain_id} is not in Starting XI"
    return True, "Captaincy valid"


def compute_transaction_hash(
    team_id: int,
    gameweek: int,
    transfers: List[Dict[str, int]],
    starting_xi: List[int],
    bench_order: List[int],
    captain_id: int,
    vice_captain_id: int,
    chip: Optional[str] = None
) -> str:
    """
    Computes a deterministic idempotency hash for a transaction.
    """
    # Sort transfers for deterministic hashing
    norm_transfers = sorted(
        transfers,
        key=lambda t: (t.get("element_out", 0), t.get("element_in", 0))
    )
    payload = {
        "team_id": team_id,
        "gameweek": gameweek,
        "transfers": norm_transfers,
        "starting_xi": sorted(starting_xi),
        "bench_order": bench_order,
        "captain_id": captain_id,
        "vice_captain_id": vice_captain_id,
        "chip": chip
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
