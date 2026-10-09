"""Features must be point-in-time: a row can never see its own gameweek or anything later."""

import numpy as np
import pandas as pd

from fpl_bot.core.features import build_features, feature_columns
from fpl_bot.data.history import COLUMNS, STAT_COLUMNS

TEAMS = ["A", "B", "C", "D"]


def synthetic_frame(rounds: int = 8, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for r in range(1, rounds + 1):
        pairs = [("A", "B"), ("C", "D")] if r % 2 else [("A", "C"), ("B", "D")]
        for k, (home, away) in enumerate(pairs):
            fixture = r * 10 + k
            goals = (int(rng.integers(0, 4)), int(rng.integers(0, 4)))
            for team, opp, is_home in ((home, away, True), (away, home, False)):
                for i in range(6):
                    mins = int(rng.choice([0, 30, 70, 90]))
                    row = {c: 0.0 for c in STAT_COLUMNS}
                    row.update(
                        minutes=mins, starts=float(mins >= 60), total_points=int(rng.integers(0, 12)),
                        xg=float(rng.random()), xa=float(rng.random()), bps=int(rng.integers(0, 40)),
                    )
                    row.update(
                        season="2025-26", season_idx=2025, name=f"{team}{i}", position=1 + i % 4, team=team,
                        opp=opp, round=r, fixture=fixture, was_home=is_home,
                        kickoff=pd.Timestamp("2025-08-01", tz="UTC") + pd.Timedelta(days=7 * r),
                        value=50 + i, team_goals=goals[0] if is_home else goals[1],
                        opp_goals=goals[1] if is_home else goals[0], ep=np.nan, played=True,
                    )
                    rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)


def _sorted(df, cols):
    return df.sort_values(["round", "fixture", "name"]).reset_index(drop=True)[cols].fillna(-999.0)


def test_later_gameweeks_do_not_change_earlier_features():
    full = build_features(synthetic_frame(8))
    cols = feature_columns(full)
    early = build_features(synthetic_frame(8).query("round <= 5"))
    a = _sorted(full[full["round"] <= 5], cols)
    b = _sorted(early, cols)
    pd.testing.assert_frame_equal(a, b)


def test_a_rows_own_outcome_never_reaches_its_features():
    base = synthetic_frame(8)
    tampered = base.copy()
    mask = tampered["round"] == 6
    for col in ("minutes", "total_points", "xg", "xa", "bps", "team_goals", "opp_goals"):
        tampered.loc[mask, col] = tampered.loc[mask, col] + 25
    cols = feature_columns(build_features(base))
    a = _sorted(build_features(base).query("round == 6"), cols)
    b = _sorted(build_features(tampered).query("round == 6"), cols)
    pd.testing.assert_frame_equal(a, b)


def test_future_rows_with_nan_stats_get_features():
    frame = synthetic_frame(6)
    future = frame[frame["round"] == 6].copy()
    future["round"] = 7
    future["fixture"] = future["fixture"] + 100
    future["played"] = False
    future[STAT_COLUMNS + ["team_goals", "opp_goals"]] = np.nan
    feats = build_features(pd.concat([frame, future], ignore_index=True))
    target = feats[feats["round"] == 7]
    assert len(target) == len(future)
    assert target["pts_avg_5"].notna().all()
    assert target["heuristic_xp"].notna().all()
