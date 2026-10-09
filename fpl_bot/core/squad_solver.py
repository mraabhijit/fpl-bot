"""
Integer-programming squad selector (PuLP / CBC).

Chooses the 15-man squad, starting XI and captain that maximise expected points for one gameweek,
net of transfer hits, subject to the budget, 2/5/5/3 shape, max 3 per club and legal formations.
With ``free_transfers >= 15`` and no owned players it builds a squad from scratch (GW1, Wildcard, Free Hit).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pulp

SQUAD_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}
HIT_COST = 4.0
CANDIDATES_PER_POSITION = 45


@dataclass
class Candidate:
    id: int
    position: int  # 1 GKP, 2 DEF, 3 MID, 4 FWD
    team: int
    price: int  # cost to buy, tenths of a million
    xp: float
    sell_price: Optional[int] = None  # set for owned players, tenths of a million


@dataclass
class SolverResult:
    squad: List[int]
    starting_xi: List[int]
    captain: int
    transfers_in: List[int]
    transfers_out: List[int]
    hits: int
    objective: float  # expected points incl. captain & bench weight, net of hit/transfer costs
    xi_xp: float = 0.0
    details: Dict[str, float] = field(default_factory=dict)


def solve_squad(
    candidates: List[Candidate],
    owned: List[int],
    bank: int,
    free_transfers: int,
    bench_weight: float = 0.12,
    hit_cost: float = HIT_COST,
    free_transfer_cost: float = 0.6,
    max_transfers: int = 5,
    time_limit: int = 30,
) -> SolverResult:
    """
    ``bank`` and prices are in tenths of a million. ``free_transfer_cost`` is the opportunity cost
    charged per free transfer used (a banked transfer is worth something), so churn needs a real gain.
    """
    owned_set = set(owned)
    by_id = {c.id: c for c in candidates}
    for pid in owned_set:
        if pid not in by_id:
            raise ValueError(f"owned player {pid} missing from candidates")

    # Prune to the best N per position (always keep owned players) to keep the model small.
    keep = set(owned_set)
    for pos in SQUAD_SHAPE:
        ranked = sorted((c for c in candidates if c.position == pos), key=lambda c: c.xp, reverse=True)
        keep.update(c.id for c in ranked[:CANDIDATES_PER_POSITION])
        # cheap enablers: the best-value cheap players per position keep the budget feasible
        cheap = sorted((c for c in candidates if c.position == pos), key=lambda c: (c.price, -c.xp))
        keep.update(c.id for c in cheap[:6])
    pool = [by_id[i] for i in keep]

    prob = pulp.LpProblem("fpl_squad", pulp.LpMaximize)
    x = {c.id: pulp.LpVariable(f"x_{c.id}", cat="Binary") for c in pool}
    s = {c.id: pulp.LpVariable(f"s_{c.id}", cat="Binary") for c in pool}
    cap = {c.id: pulp.LpVariable(f"c_{c.id}", cat="Binary") for c in pool}
    hits = pulp.LpVariable("hits", lowBound=0, cat="Integer")

    n_in = pulp.lpSum(x[c.id] for c in pool if c.id not in owned_set)
    unlimited = free_transfers >= 15
    xi_value = pulp.lpSum(c.xp * (s[c.id] + cap[c.id]) for c in pool)
    bench_value = pulp.lpSum(bench_weight * c.xp * (x[c.id] - s[c.id]) for c in pool)
    if unlimited:
        prob += xi_value + bench_value
    else:
        free_used = n_in - hits
        prob += xi_value + bench_value - hit_cost * hits - free_transfer_cost * free_used
        prob += hits >= n_in - free_transfers
        prob += n_in <= max_transfers
    if unlimited:
        prob += hits == 0

    for pos, n in SQUAD_SHAPE.items():
        prob += pulp.lpSum(x[c.id] for c in pool if c.position == pos) == n
        prob += pulp.lpSum(s[c.id] for c in pool if c.position == pos) >= XI_MIN[pos]
        prob += pulp.lpSum(s[c.id] for c in pool if c.position == pos) <= XI_MAX[pos]
    prob += pulp.lpSum(s.values()) == 11
    prob += pulp.lpSum(cap.values()) == 1
    for c in pool:
        prob += s[c.id] <= x[c.id]
        prob += cap[c.id] <= s[c.id]
    for team in {c.team for c in pool}:
        prob += pulp.lpSum(x[c.id] for c in pool if c.team == team) <= 3

    # Budget: retained players count at selling price, new signings at purchase price.
    spend = pulp.lpSum(
        (c.sell_price if c.id in owned_set and c.sell_price is not None else c.price) * x[c.id] for c in pool
    )
    owned_value = sum((by_id[i].sell_price if by_id[i].sell_price is not None else by_id[i].price) for i in owned_set)
    prob += spend <= bank + owned_value

    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=time_limit))
    if pulp.LpStatus[prob.status] != "Optimal":
        raise RuntimeError(f"squad solver failed: {pulp.LpStatus[prob.status]}")

    squad = [c.id for c in pool if x[c.id].value() > 0.5]
    xi = [c.id for c in pool if s[c.id].value() > 0.5]
    captain = next(c.id for c in pool if cap[c.id].value() > 0.5)
    t_in = [i for i in squad if i not in owned_set]
    t_out = [i for i in owned_set if i not in set(squad)]
    n_hits = 0 if unlimited else max(0, len(t_in) - free_transfers)
    return SolverResult(
        squad=squad,
        starting_xi=xi,
        captain=captain,
        transfers_in=t_in,
        transfers_out=t_out,
        hits=n_hits,
        objective=float(pulp.value(prob.objective)),
        xi_xp=sum(by_id[i].xp for i in xi) + by_id[captain].xp,
    )
