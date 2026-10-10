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


def _real_squad(xps):
    squad = _squad()
    projections = _projections(squad)
    for p, xp in zip(squad, xps):
        projections[p.id].expected_fpl_points = xp
    return squad, projections


# GKP x2, DEF x5, MID x5, FWD x3
XPS = [4.0, 3.0, 3.7, 2.2, 2.1, 1.8, 0.4, 6.2, 4.5, 4.4, 3.9, 1.4, 6.2, 1.8, 0.0]


def test_explanations_cover_every_player_and_explain_the_bench():
    agent = OptimizationAgent()
    squad, projections = _real_squad(XPS)
    result = agent.optimize_lineup_and_captain(squad, projections, {})
    expl = agent.explain_selection(squad, projections, {}, result)

    assert set(expl) == {p.id for p in squad}
    xi, bench = set(result[0]), result[1]
    for p in squad:
        e = expl[p.id]
        assert e["xp"] == round(projections[p.id].expected_fpl_points, 2)
        if p.id in xi:
            assert e["role"] in ("Starting XI", "Captain", "Vice-captain")
        else:
            assert e["role"].startswith("Bench")
            if p.element_type != 1:
                assert any("Left out by formation" in n or "Below the" in n for n in e["notes"])
    assert expl[result[2]]["role"] == "Captain"
    assert any("gap" in n for n in expl[result[2]]["notes"])


def test_formation_alternative_gap_matches_the_option_table():
    agent = OptimizationAgent()
    squad, projections = _real_squad(XPS)
    result = agent.optimize_lineup_and_captain(squad, projections, {})
    info, expl = result[9], agent.explain_selection(squad, projections, {}, result)
    chosen = info["chosen"]
    chosen_xi = next(o["xi_xp"] for o in info["options"] if o["counts"] == chosen)
    benched_fwd = next(p for p in squad if p.element_type == 4 and p.id not in set(result[0]))
    alts = [o for o in info["options"] if o["counts"][2] > chosen[2]]
    if alts:
        delta = max(o["xi_xp"] for o in alts) - chosen_xi
        assert f"{delta:+.2f}" in " ".join(expl[benched_fwd.id]["notes"])
    assert all(o["xi_xp"] <= max(x["xi_xp"] for x in info["options"]) for o in info["options"])


def test_explanation_block_survives_the_database_round_trip(tmp_path):
    from fpl_bot.core.database import Database

    d = Database(tmp_path / "t.db")
    d.save_recommendation({
        "gameweek": 1, "captain_id": 1, "vice_captain_id": 2,
        "selection_explanations": {"7": {"role": "Starting XI", "xp": 3.2, "notes": ["x"]}},
    })
    assert d.get_latest_recommendation(1)["selection_explanations"]["7"]["xp"] == 3.2


def test_unavailable_bench_player_is_explained_by_news_not_formation():
    from fpl_bot.core.models import PlayerAvailability

    agent = OptimizationAgent()
    squad, projections = _real_squad(XPS)
    injured = squad[-1]  # the 0.0 xP forward
    avail = {injured.id: PlayerAvailability(
        player_id=injured.id, availability_probability=0.0, start_probability=0.0, minutes_probability=0.0,
        rotation_risk=0.0, injury_risk=1.0, news="Thigh injury")}
    result = agent.optimize_lineup_and_captain(squad, projections, avail)
    notes = agent.explain_selection(squad, projections, avail, result)[injured.id]["notes"]
    assert any("Unavailable: Thigh injury" in n for n in notes)
    assert not any("Left out by formation" in n for n in notes)
