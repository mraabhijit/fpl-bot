import pytest
from fpl_bot.core.models import Player, PlayerProjection, PlayerAvailability
from fpl_bot.agents.optimization_agent import OptimizationAgent


def make_player(pid: int, pos: int, name: str, cost: int = 50) -> Player:
    pos_names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return Player(
        id=pid,
        web_name=name,
        first_name="Test",
        second_name=name,
        team_id=pid % 10 + 1,
        element_type=pos,
        position_name=pos_names[pos],
        now_cost=cost
    )


def test_subs_sequence_formation_legality():
    agent = OptimizationAgent()

    # Create 11 starters: 1 GKP, 3 DEF, 5 MID, 2 FWD (3-5-2 formation)
    # The 3 DEF starters have some rotation risk (avail_prob = 0.70)
    gk_start = make_player(1, 1, "Raya")
    defs_start = [make_player(2, 2, "Def1"), make_player(3, 2, "Def2"), make_player(4, 2, "Def3")]
    mids_start = [make_player(5, 3, "Mid1"), make_player(6, 3, "Mid2"), make_player(7, 3, "Mid3"), make_player(8, 3, "Mid4"), make_player(9, 3, "Mid5")]
    fwds_start = [make_player(10, 4, "Fwd1"), make_player(11, 4, "Fwd2")]

    starting_xi = [gk_start] + defs_start + mids_start + fwds_start

    # Bench: GK, 1 DEF, 1 MID, 1 FWD
    bench_gk = make_player(12, 1, "BenchGK")
    sub_def = make_player(13, 2, "SubDef")
    sub_mid = make_player(14, 3, "SubMid")
    sub_fwd = make_player(15, 4, "SubFwd")
    bench_outfield = [sub_def, sub_mid, sub_fwd]

    # Projections
    projections = {}
    for p in starting_xi + [bench_gk] + bench_outfield:
        projections[p.id] = PlayerProjection(
            player_id=p.id,
            expected_minutes=90.0,
            expected_starts=0.9,
            expected_goals=0.2,
            expected_assists=0.1,
            expected_clean_sheet_probability=0.3,
            expected_bonus=0.5,
            expected_cards=0.1,
            expected_goals_conceded=1.0,
            expected_penalty_probability=0.0,
            expected_set_piece_probability=0.0,
            expected_fpl_points=5.0 if p.id in (10, 11) else 4.0,
            confidence=0.8
        )

    # Higher projected points on SubMid (6.0 pts) vs SubDef (4.0 pts)
    projections[sub_mid.id].expected_fpl_points = 6.0
    projections[sub_def.id].expected_fpl_points = 4.0
    projections[sub_fwd.id].expected_fpl_points = 3.0

    # Availabilities: Def3 is doubtful (0.40 availability)
    availabilities = {}
    for p in starting_xi + [bench_gk] + bench_outfield:
        availabilities[p.id] = PlayerAvailability(
            player_id=p.id,
            availability_probability=0.95,
            start_probability=0.90,
            minutes_probability=0.90,
            rotation_risk=0.1,
            injury_risk=0.05
        )
    # Give Def3 rotation risk
    availabilities[4].availability_probability = 0.30
    availabilities[4].start_probability = 0.30

    (
        bench_order,
        xi_xp,
        bench_xp,
        total_squad_xp,
        sub_probs,
        reasons
    ) = agent.evaluate_squad_and_bench_sequence(
        starting_xi=starting_xi,
        bench_outfield=bench_outfield,
        starting_gk=gk_start,
        bench_gk=bench_gk,
        captain=starting_xi[9],
        vice_captain=starting_xi[10],
        projections=projections,
        availabilities=availabilities
    )

    # Slot 12 must be GK sub
    assert bench_order[0] == bench_gk.id
    # Bench outfield order has 3 elements
    assert len(bench_order) == 4

    # Check that SubDef has a positive autosub probability because Def3 has high rotation risk
    # and in 3-5-2, dropping Def3 leaves 2 DEF on pitch which requires SubDef!
    assert sub_probs[sub_def.id] > 0.05
    assert total_squad_xp > xi_xp  # Bench autosubs provide positive expected insurance value
    assert bench_xp > 0.0
