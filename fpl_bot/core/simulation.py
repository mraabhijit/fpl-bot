"""
Walk-forward season simulation. Each gameweek the strategy only sees predictions made from earlier
gameweeks; the chosen team is then scored against the real outcome with captaincy and autosubs.
Used by the backtest, which is leak-free because features are point-in-time and the model is only
ever fitted on rows from before the gameweek being predicted.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from fpl_bot.core.model import PointsModel
from fpl_bot.core.squad_solver import Candidate, SolverResult, solve_squad

MAX_BANKED_TRANSFERS = 5
START_BUDGET = 1000


def score_lineup(
    xi: List[int], bench_order: List[int], captain: int, vice: int,
    points: Dict[int, float], minutes: Dict[int, float], position: Dict[int, int],
) -> float:
    """Actual points for a lineup: captain doubling (vice if captain did not play) and FPL autosubs."""
    played = lambda i: minutes.get(i, 0) > 0  # noqa: E731
    active = [i for i in xi if played(i)]
    gk_start = next(i for i in xi if position[i] == 1)
    bench_gk = next((i for i in bench_order if position[i] == 1), None)
    if not played(gk_start) and bench_gk is not None and played(bench_gk):
        active.append(bench_gk)

    counts = {p: sum(1 for i in active if position[i] == p) for p in (2, 3, 4)}
    missing_outfield = sum(1 for i in xi if position[i] != 1 and not played(i))
    outfield_bench = [i for i in bench_order if position[i] != 1]
    for idx, sub in enumerate(outfield_bench):
        if missing_outfield <= 0:
            break
        if not played(sub):
            continue
        trial = dict(counts)
        trial[position[sub]] += 1
        if _formation_ok(trial, outfield_bench[idx + 1:], position):
            active.append(sub)
            counts = trial
            missing_outfield -= 1
    total = sum(points.get(i, 0.0) for i in active)
    cap = captain if played(captain) else (vice if played(vice) else None)
    if cap is not None:
        total += points.get(cap, 0.0)
    return total


def _formation_ok(counts: Dict[int, int], remaining_bench: List[int], position: Dict[int, int]) -> bool:
    """Shape stays within the maxima and the minima can still be reached from the remaining bench."""
    if counts[2] > 5 or counts[3] > 5 or counts[4] > 3:
        return False
    spare = {p: sum(1 for i in remaining_bench if position[i] == p) for p in (2, 3, 4)}
    return all(counts[p] + spare[p] >= m for p, m in ((2, 3), (3, 2), (4, 1)))


@dataclass
class SeasonResult:
    rounds: pd.DataFrame  # one row per simulated gameweek
    total_points: float = 0.0
    total_hits: int = 0
    transfers: List[Dict] = field(default_factory=list)


def sell_price(purchase: int, current: int) -> int:
    """FPL selling rule: keep half of any price rise, rounded down."""
    return current if current <= purchase else purchase + (current - purchase) // 2


def walk_forward_predictions(
    feats: pd.DataFrame, season_idx: int, start_round: int = 1, retrain_every: int = 3,
    params: Optional[Dict] = None, exclude_prefixes: tuple = (),
) -> pd.Series:
    """Out-of-sample fixture-level xp for every row of ``season_idx`` from ``start_round`` on."""
    t = feats["season_idx"] * 100 + feats["round"]
    season_rows = feats[feats["season_idx"] == season_idx]
    preds = pd.Series(np.nan, index=feats.index, name="xp")
    model = None
    for r in sorted(season_rows["round"].unique()):
        if r < start_round:
            continue
        if model is None or (r - start_round) % retrain_every == 0:
            train = feats[(t < season_idx * 100 + r) & feats["played"]]
            model = PointsModel(params, exclude_prefixes).fit(train)
        rows = season_rows[season_rows["round"] == r]
        preds.loc[rows.index] = model.predict_fixtures(rows)
    return preds


def simulate_season(
    feats: pd.DataFrame, xp_col: str, season_idx: int, start_round: int = 1, end_round: Optional[int] = None,
    allow_hits: bool = True, max_transfers: int = 5, verbose: bool = False,
) -> SeasonResult:
    """
    Plays one season with the strategy that ranks players by ``feats[xp_col]`` (fixture level).
    GW ``start_round`` builds a fresh £100m squad; later gameweeks use free transfers / hits.
    """
    season = feats[feats["season_idx"] == season_idx].copy()
    season["xp_use"] = season[xp_col].fillna(0.0)
    rounds = sorted(r for r in season["round"].unique() if r >= start_round and (end_round is None or r <= end_round))

    info: Dict[str, Dict] = {}  # last known position/team/price by player
    squad: Dict[str, int] = {}  # name -> purchase price
    bank = START_BUDGET
    ft = 1
    rows_out, transfers_log = [], []

    for r in rounds:
        rr = season[season["round"] == r]
        agg = rr.groupby("name").agg(
            position=("position", "first"), team=("team", "first"), value=("value", "last"),
            xp=("xp_use", "sum"), pts=("total_points", "sum"), mins=("minutes", "sum"),
        )
        for name, row in agg.iterrows():
            info[name] = {"position": int(row.position), "team": row.team, "value": int(row.value)}
        # Players without a fixture this round are still ownable (xp 0).
        all_names = list(info.keys())
        xp = agg["xp"].reindex(all_names).fillna(0.0)
        pts = agg["pts"].reindex(all_names).fillna(0.0).to_dict()
        mins = agg["mins"].reindex(all_names).fillna(0.0).to_dict()

        ids = {n: i for i, n in enumerate(all_names)}
        names = {i: n for n, i in ids.items()}
        cands = []
        for n in all_names:
            price = info[n]["value"]
            cand = Candidate(ids[n], info[n]["position"], hash(info[n]["team"]) % 10**9, price, float(xp[n]))
            if n in squad:
                cand.sell_price = sell_price(squad[n], price)
            cands.append(cand)

        first = not squad
        res: SolverResult = solve_squad(
            cands, owned=[ids[n] for n in squad], bank=bank,
            free_transfers=15 if first else ft,
            max_transfers=max_transfers if allow_hits else min(ft, max_transfers),
        )
        # apply transfers
        for pid in res.transfers_out:
            n = names[pid]
            bank += sell_price(squad.pop(n), info[n]["value"])
        for pid in res.transfers_in:
            n = names[pid]
            bank -= info[n]["value"]
            squad[n] = info[n]["value"]
            if not first:
                transfers_log.append({"round": r, "in": n})

        position = {ids[n]: info[n]["position"] for n in squad}
        xi = res.starting_xi
        xi_sorted = sorted(xi, key=lambda i: float(xp[names[i]]), reverse=True)
        captain, vice = res.captain, next(i for i in xi_sorted if i != res.captain)
        bench = [i for i in res.squad if i not in set(xi)]
        bench_gk = [i for i in bench if position[i] == 1]
        bench_out = sorted((i for i in bench if position[i] != 1), key=lambda i: float(xp[names[i]]), reverse=True)
        bench_order = bench_gk + bench_out

        pid_pts = {ids[n]: pts[n] for n in squad}
        pid_min = {ids[n]: mins[n] for n in squad}
        gross = score_lineup(xi, bench_order, captain, vice, pid_pts, pid_min, position)
        hit_pts = 4 * res.hits if not first else 0
        rows_out.append({
            "round": r, "points": gross - hit_pts, "gross": gross, "hits": res.hits if not first else 0,
            "transfers": 0 if first else len(res.transfers_in), "predicted": sum(float(xp[names[i]]) for i in xi) + float(xp[names[captain]]),
            "bank": bank, "captain": names[captain],
            "captain_points": pid_pts[captain], "vice_points": pid_pts[vice],
            "captain_best": pid_pts[captain] >= max(pid_pts[i] for i in xi),
            "bench_points": sum(pid_pts[i] for i in bench_order),
        })
        if verbose:
            print(rows_out[-1])
        used = 0 if first else min(len(res.transfers_in), ft)
        ft = min(MAX_BANKED_TRANSFERS, ft - used + 1)

    df = pd.DataFrame(rows_out)
    return SeasonResult(rounds=df, total_points=float(df["points"].sum()), total_hits=int(df["hits"].sum()), transfers=transfers_log)
