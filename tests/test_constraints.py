import pytest
from fpl_bot.core.models import Player
from fpl_bot.core.constraints import (
    validate_formation,
    validate_squad_composition,
    validate_captaincy,
    compute_transaction_hash,
    VALID_FORMATIONS
)


def make_dummy_player(pid: int, pos: int, team: int = 1, cost: int = 50) -> Player:
    pos_names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return Player(
        id=pid,
        web_name=f"Player_{pid}",
        first_name="Test",
        second_name=f"User{pid}",
        team_id=team,
        element_type=pos,
        position_name=pos_names[pos],
        now_cost=cost
    )


def test_validate_formation():
    # Valid 3-5-2: 1 GKP, 3 DEF, 5 MID, 2 FWD
    xi = (
        [make_dummy_player(1, 1)]
        + [make_dummy_player(i, 2) for i in range(2, 5)]
        + [make_dummy_player(i, 3) for i in range(5, 10)]
        + [make_dummy_player(i, 4) for i in range(10, 12)]
    )
    valid, msg = validate_formation(xi)
    assert valid is True

    # Invalid formation: 2 GKP in Starting XI
    invalid_xi = (
        [make_dummy_player(1, 1), make_dummy_player(2, 1)]
        + [make_dummy_player(i, 2) for i in range(3, 6)]
        + [make_dummy_player(i, 3) for i in range(6, 10)]
        + [make_dummy_player(i, 4) for i in range(10, 12)]
    )
    valid, msg = validate_formation(invalid_xi)
    assert valid is False
    assert "exactly 1 GKP" in msg


def test_validate_squad_composition():
    # Valid squad: 2 GKP, 5 DEF, 5 MID, 3 FWD with distinct teams
    squad = (
        [make_dummy_player(1, 1, team=1), make_dummy_player(2, 1, team=2)]
        + [make_dummy_player(i, 2, team=i) for i in range(3, 8)]
        + [make_dummy_player(i, 3, team=i) for i in range(8, 13)]
        + [make_dummy_player(i, 4, team=i) for i in range(13, 16)]
    )
    valid, msg = validate_squad_composition(squad)
    assert valid is True

    # Invalid: 4 players from same team
    squad_overflow = (
        [make_dummy_player(1, 1, team=1), make_dummy_player(2, 1, team=1)]
        + [make_dummy_player(3, 2, team=1), make_dummy_player(4, 2, team=1)]
        + [make_dummy_player(i, 2, team=i) for i in range(5, 8)]
        + [make_dummy_player(i, 3, team=i) for i in range(8, 13)]
        + [make_dummy_player(i, 4, team=i) for i in range(13, 16)]
    )
    valid, msg = validate_squad_composition(squad_overflow)
    assert valid is False
    assert "Exceeded limit of 3 players" in msg


def test_validate_captaincy():
    xi_ids = list(range(1, 12))
    # Valid: captain=1, vice=2 (both in XI)
    valid, msg = validate_captaincy(xi_ids, 1, 2)
    assert valid is True

    # Invalid: captain and vice same
    valid, msg = validate_captaincy(xi_ids, 1, 1)
    assert valid is False

    # Invalid: captain not in XI
    valid, msg = validate_captaincy(xi_ids, 15, 2)
    assert valid is False


def test_compute_transaction_hash_idempotency():
    h1 = compute_transaction_hash(
        team_id=6834344,
        gameweek=5,
        transfers=[{"element_in": 10, "element_out": 20}],
        starting_xi=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        bench_order=[12, 13, 14, 15],
        captain_id=10,
        vice_captain_id=9,
        chip=None
    )
    h2 = compute_transaction_hash(
        team_id=6834344,
        gameweek=5,
        transfers=[{"element_in": 10, "element_out": 20}],
        starting_xi=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        bench_order=[12, 13, 14, 15],
        captain_id=10,
        vice_captain_id=9,
        chip=None
    )
    assert h1 == h2
    assert len(h1) == 64
