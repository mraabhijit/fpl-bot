from fpl_bot.agents.optimization_agent import OptimizationAgent
from fpl_bot.core.models import Player, PlayerProjection


def _player(pid: int, pos: int) -> Player:
    names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return Player(
        id=pid, web_name=f"P{pid}", first_name="T", second_name=f"P{pid}", team_id=pid % 10 + 1,
        element_type=pos, position_name=names[pos], now_cost=50,
    )


def _squad():
    # 2 GKP, 5 DEF, 5 MID, 3 FWD: every formation in VALID_FORMATIONS is available
    layout = [1] * 2 + [2] * 5 + [3] * 5 + [4] * 3
    return [_player(i + 1, pos) for i, pos in enumerate(layout)]


def _projections(squad):
    return {
        p.id: PlayerProjection(
            player_id=p.id, expected_minutes=90.0, expected_starts=0.9, expected_goals=0.2, expected_assists=0.1,
            expected_clean_sheet_probability=0.3, expected_bonus=0.5, expected_cards=0.1, expected_goals_conceded=1.0,
            expected_penalty_probability=0.0, expected_set_piece_probability=0.0, expected_fpl_points=4.0, confidence=0.8,
        )
        for p in squad
    }


def _pick_formation(monkeypatch, scores):
    """Runs the formation search with scripted (xi_xp, bench_xp) per formation; others score a low XI."""
    squad = _squad()
    by_id = {p.id: p for p in squad}

    def fake(self, starting_xi, bench_outfield, starting_gk, bench_gk, captain, vice_captain, projections, availabilities):
        counts = tuple(sum(1 for p in starting_xi if p.element_type == t) for t in (2, 3, 4))
        xi_xp, bench_xp = scores.get(counts, (40.0, 0.0))
        return [bench_gk.id] + [p.id for p in bench_outfield], xi_xp, bench_xp, xi_xp + bench_xp, {}, []

    monkeypatch.setattr(OptimizationAgent, "evaluate_squad_and_bench_sequence", fake)
    xi_ids = OptimizationAgent().optimize_lineup_and_captain(squad, _projections(squad), {})[0]
    return tuple(sum(1 for i in xi_ids if by_id[i].element_type == t) for t in (2, 3, 4))


def test_xi_points_decide_even_when_bench_cover_favours_another_formation(monkeypatch):
    scores = {(3, 4, 3): (50.0, 0.1), (4, 4, 2): (49.5, 2.0)}
    assert _pick_formation(monkeypatch, scores) == (3, 4, 3)


def test_bench_cover_breaks_a_tie_within_tolerance(monkeypatch):
    scores = {(3, 4, 3): (50.0, 0.2), (4, 4, 2): (49.95, 0.9)}
    assert _pick_formation(monkeypatch, scores) == (4, 4, 2)


def test_bench_cover_ignored_outside_tolerance(monkeypatch):
    scores = {(3, 4, 3): (50.0, 0.2), (4, 4, 2): (49.85, 5.0)}
    assert _pick_formation(monkeypatch, scores) == (3, 4, 3)


def test_full_tie_goes_to_earlier_formation(monkeypatch):
    scores = {(3, 4, 3): (50.0, 0.5), (4, 4, 2): (50.0, 0.5)}
    assert _pick_formation(monkeypatch, scores) == (3, 4, 3)
