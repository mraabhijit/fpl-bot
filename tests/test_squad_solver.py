import random

import pytest

from fpl_bot.core.squad_solver import Candidate, solve_squad, SQUAD_SHAPE, XI_MAX, XI_MIN


def make_pool(seed: int = 1, per_pos=None):
    rnd = random.Random(seed)
    per_pos = per_pos or {1: 8, 2: 20, 3: 20, 4: 12}
    pool, pid = [], 0
    for pos, n in per_pos.items():
        for _ in range(n):
            pid += 1
            price = rnd.randint(40, 120)
            pool.append(Candidate(pid, pos, rnd.randint(1, 10), price, round(price / 25 + rnd.random() * 2, 2)))
    return pool


def check_valid(res, pool, budget):
    by_id = {c.id: c for c in pool}
    assert len(res.squad) == 15 and len(set(res.squad)) == 15
    for pos, n in SQUAD_SHAPE.items():
        assert sum(by_id[i].position == pos for i in res.squad) == n
    for team in {by_id[i].team for i in res.squad}:
        assert sum(by_id[i].team == team for i in res.squad) <= 3
    assert len(res.starting_xi) == 11 and set(res.starting_xi) <= set(res.squad)
    for pos in SQUAD_SHAPE:
        assert XI_MIN[pos] <= sum(by_id[i].position == pos for i in res.starting_xi) <= XI_MAX[pos]
    assert res.captain in res.starting_xi
    assert sum(by_id[i].price for i in res.squad) <= budget


def test_builds_valid_squad_from_scratch_within_budget():
    pool = make_pool()
    res = solve_squad(pool, owned=[], bank=1000, free_transfers=15)
    check_valid(res, pool, 1000)
    assert res.hits == 0


def test_captain_is_best_xi_player():
    pool = make_pool(2)
    res = solve_squad(pool, owned=[], bank=1000, free_transfers=15)
    by_id = {c.id: c for c in pool}
    assert by_id[res.captain].xp == max(by_id[i].xp for i in res.starting_xi)


def _optimal_owned(pool):
    """Start from the best possible squad, with selling prices set."""
    res = solve_squad(pool, owned=[], bank=1000, free_transfers=15)
    for c in pool:
        if c.id in res.squad:
            c.sell_price = c.price
    return res


def _injure(pool, ids):
    by_id = {c.id: c for c in pool}
    for i in ids:
        by_id[i].xp = 0.0


def test_optimal_squad_makes_no_transfers():
    pool = make_pool(3)
    owned = _optimal_owned(pool)
    res = solve_squad(pool, owned=owned.squad, bank=0, free_transfers=1)
    assert res.transfers_in == [] and res.hits == 0


def _injure_position(pool, owned, position):
    """Zero every owned player of a position, so benching cannot cover for them."""
    by_id = {c.id: c for c in pool}
    victims = [i for i in owned.squad if by_id[i].position == position]
    _injure(pool, victims)
    return victims


def test_free_transfer_replaces_an_injured_player_without_a_hit():
    pool = make_pool(3)
    owned = _optimal_owned(pool)
    victims = _injure_position(pool, owned, 3)
    res = solve_squad(pool, owned=owned.squad, bank=0, free_transfers=1, max_transfers=1)
    assert len(res.transfers_in) == 1 and res.hits == 0
    assert res.transfers_out[0] in victims


def test_hits_are_priced_and_never_forced():
    pool = make_pool(4)
    owned = _optimal_owned(pool)
    _injure_position(pool, owned, 3)
    res = solve_squad(pool, owned=owned.squad, bank=0, free_transfers=1, max_transfers=4)
    assert res.hits == max(0, len(res.transfers_in) - 1)
    # with an absurd hit price the solver never pays one
    no_hit = solve_squad(pool, owned=owned.squad, bank=0, free_transfers=1, hit_cost=100.0, max_transfers=4)
    assert no_hit.hits == 0 and len(no_hit.transfers_in) <= 1
    assert res.objective >= no_hit.objective - 1e-6


def test_budget_blocks_unaffordable_transfer():
    pool = make_pool(5)
    owned = _optimal_owned(pool).squad
    by_id = {c.id: c for c in pool}
    weak = owned[7]
    pool.append(Candidate(950, by_id[weak].position, 95, by_id[weak].price + 50, by_id[weak].xp + 20.0))
    res = solve_squad(pool, owned=owned, bank=10, free_transfers=1, max_transfers=1)
    assert 950 not in res.squad


def test_missing_owned_candidate_raises():
    pool = make_pool(6)
    with pytest.raises(ValueError):
        solve_squad(pool, owned=[9999], bank=0, free_transfers=1)
