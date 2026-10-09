"""
Point-in-time feature engineering.

``build_features`` takes the fixture-level frame produced by ``fpl_bot.data.history`` (played rows plus
future rows with NaN stats) and returns the same rows with predictive features. Every rolling feature
is computed on stats of *strictly earlier gameweeks* (shift(1) at gameweek level), so the training
path and the inference path are identical and a future row can never see its own outcome.
"""

from typing import List, Tuple

import numpy as np
import pandas as pd

WINDOWS = (3, 5, 10)
TEAM_WINDOWS = (6, 15)
PLAYER_STATS = [
    "minutes", "starts", "total_points", "xg", "xa", "xgc", "goals_scored", "assists",
    "clean_sheets", "bonus", "bps", "saves", "ict", "defensive_contribution", "yellow_cards",
    "played_any", "played60",
]
GOAL_PTS = {1: 10.0, 2: 6.0, 3: 5.0, 4: 4.0}
CS_PTS = {1: 4.0, 2: 4.0, 3: 1.0, 4: 0.0}
LEAGUE_GOALS = 1.4  # prior goals per team per match for teams with no history
LEAGUE_PPG = 1.37   # prior league points per match
VENUE_WINDOW = 8
ALLOWED_WINDOW = 10
ELO_K = 14.0
ELO_HOME_ADV = 60.0
EWM_HALFLIFE = 3.0


def _roll_sum(shifted: pd.DataFrame, key: pd.Series, cols: List[str], w: int) -> pd.DataFrame:
    r = shifted[cols].groupby(key, sort=False).rolling(w, min_periods=1).sum()
    return r.reset_index(level=0, drop=True)


def _player_round_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling per-player features at (name, season, round) level, using earlier rounds only."""
    g = df.groupby(["name", "season_idx", "round"], sort=False)
    pr = g[[c for c in PLAYER_STATS if c not in ("played_any", "played60")]].sum(min_count=1)
    pr["n_fix"] = g.size()
    pr = pr.reset_index()
    pr["t"] = pr["season_idx"] * 100 + pr["round"]
    pr["played_any"] = (pr["minutes"] > 0).astype(float).where(pr["minutes"].notna())
    pr["played60"] = (pr["minutes"] >= 60).astype(float).where(pr["minutes"].notna())
    pr = pr.sort_values(["name", "t"]).reset_index(drop=True)

    shifted = pr.groupby("name", sort=False)[PLAYER_STATS].shift(1)
    key = pr["name"]
    feats = {}
    for w in WINDOWS:
        s = _roll_sum(shifted, key, PLAYER_STATS, w)
        n = shifted["minutes"].groupby(key, sort=False).rolling(w, min_periods=1).count().reset_index(level=0, drop=True)
        n = n.replace(0, np.nan)
        m = s["minutes"]
        feats[f"mins_avg_{w}"] = m / n
        feats[f"start_rate_{w}"] = s["starts"] / n
        feats[f"pts_avg_{w}"] = s["total_points"] / n
        feats[f"p60_{w}"] = s["played60"] / n
        feats[f"pany_{w}"] = s["played_any"] / n
        for col, name in (("xg", "xg90"), ("xa", "xa90"), ("bonus", "bonus90"), ("bps", "bps90"),
                          ("ict", "ict90"), ("saves", "saves90"), ("defensive_contribution", "dc90"),
                          ("xgc", "xgc90"), ("goals_scored", "goals90"), ("assists", "assists90"),
                          ("yellow_cards", "yc90"), ("total_points", "pts90")):
            feats[f"{name}_{w}"] = 90.0 * s[col] / (m + 180.0)
        feats[f"cs_per60_{w}"] = s["clean_sheets"] / (s["played60"] + 1.0)
    pr["xgi"] = pr["xg"] + pr["xa"]
    for col, name in (("total_points", "pts"), ("minutes", "min"), ("xgi", "xgi"), ("bps", "bps"), ("ict", "ict")):
        feats[f"ewm_{name}"] = pr.groupby("name", sort=False)[col].transform(lambda s: s.shift(1).ewm(halflife=EWM_HALFLIFE, min_periods=1).mean())
    feats["ewm_pts_trend"] = feats["ewm_pts"] - feats["pts_avg_10"]
    feats["lag1_minutes"] = shifted["minutes"]
    feats["lag2_minutes"] = pr.groupby("name", sort=False)["minutes"].shift(2)
    feats["lag1_points"] = shifted["total_points"]
    feats["rounds_known"] = shifted["minutes"].notna().groupby(key, sort=False).cumsum()
    out = pd.concat([pr[["name", "season_idx", "round", "n_fix"]], pd.DataFrame(feats)], axis=1)
    return out


def _team_round_features(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling team attack/defence form at (team, season, round) level, using earlier rounds only."""
    tf = df.groupby(["season_idx", "round", "fixture", "team", "opp"], sort=False).agg(
        gf=("team_goals", "first"), ga=("opp_goals", "first"), xgf=("xg", lambda s: s.sum(min_count=1)),
    ).reset_index()
    opp_side = tf[["season_idx", "fixture", "team", "xgf"]].rename(columns={"team": "opp", "xgf": "xga"})
    tf = tf.merge(opp_side, on=["season_idx", "fixture", "opp"], how="left")
    tf["ppg"] = np.where(tf["gf"].isna(), np.nan, np.where(tf["gf"] > tf["ga"], 3.0, np.where(tf["gf"] == tf["ga"], 1.0, 0.0)))
    tr = tf.groupby(["team", "season_idx", "round"], sort=False)[["gf", "ga", "xgf", "xga", "ppg"]].mean().reset_index()
    tr["t"] = tr["season_idx"] * 100 + tr["round"]
    tr = tr.sort_values(["team", "t"]).reset_index(drop=True)
    cols = ["gf", "ga", "xgf", "xga", "ppg"]
    shifted = tr.groupby("team", sort=False)[cols].shift(1)
    out = tr[["team", "season_idx", "round"]].copy()
    for w in TEAM_WINDOWS:
        r = shifted.groupby(tr["team"], sort=False).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        for c in cols:
            out[f"team_{c}_{w}"] = r[c].fillna(LEAGUE_PPG if c == "ppg" else LEAGUE_GOALS)
    return out


def _fixture_table(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (fixture, side) with goals for/against and expected goals for/against."""
    tf = df.groupby(["season_idx", "round", "fixture", "team", "opp", "was_home"], sort=False).agg(
        gf=("team_goals", "first"), ga=("opp_goals", "first"), xgf=("xg", lambda s: s.sum(min_count=1)),
    ).reset_index()
    opp_side = tf[["season_idx", "fixture", "team", "xgf"]].rename(columns={"team": "opp", "xgf": "xga"})
    return tf.merge(opp_side, on=["season_idx", "fixture", "opp"], how="left")


def _venue_team_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Team attack/defence form measured only in matches at the same venue type (home matches for home sides,
    away matches for away sides), earlier rounds only. Keys: team, was_home, season_idx, round.
    """
    tf = _fixture_table(df)
    cols = ["gf", "ga", "xgf", "xga"]
    vt = tf.groupby(["team", "was_home", "season_idx", "round"], sort=False)[cols].mean().reset_index()
    vt["t"] = vt["season_idx"] * 100 + vt["round"]
    vt = vt.sort_values(["team", "was_home", "t"]).reset_index(drop=True)
    keys = [vt["team"], vt["was_home"]]
    shifted = vt.groupby(["team", "was_home"], sort=False)[cols].shift(1)
    r = shifted.groupby(keys, sort=False).rolling(VENUE_WINDOW, min_periods=1).mean().reset_index(level=[0, 1], drop=True)
    out = vt[["team", "was_home", "season_idx", "round"]].copy()
    for c in cols:
        out[f"ven_{c}"] = r[c].fillna(LEAGUE_GOALS)
    return out


def _elo_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Elo strength rating per team from results, snapshotted at the start of each gameweek and updated
    after it, so a fixture never sees its own gameweek. Ratings regress a third of the way to the mean
    between seasons. Keys: season_idx, fixture.
    """
    tf = _fixture_table(df)
    home = tf[tf["was_home"]].rename(columns={"team": "home", "opp": "away", "gf": "hg", "ga": "ag"})
    home = home[["season_idx", "round", "fixture", "home", "away", "hg", "ag"]]
    home = home.sort_values(["season_idx", "round", "fixture"])
    rating: dict = {}
    rows = []
    prev_season = None
    for (season, _rnd), grp in home.groupby(["season_idx", "round"], sort=True):
        if prev_season is not None and season != prev_season:
            rating = {t: 1500.0 + (v - 1500.0) * 0.67 for t, v in rating.items()}
        prev_season = season
        for r in grp.itertuples(index=False):
            rows.append((season, r.fixture, rating.get(r.home, 1500.0), rating.get(r.away, 1500.0)))
        for r in grp.itertuples(index=False):
            if pd.isna(r.hg) or pd.isna(r.ag):
                continue
            rh, ra = rating.get(r.home, 1500.0), rating.get(r.away, 1500.0)
            expected = 1.0 / (1.0 + 10 ** (-(rh - ra + ELO_HOME_ADV) / 400.0))
            actual = 1.0 if r.hg > r.ag else (0.5 if r.hg == r.ag else 0.0)
            delta = ELO_K * (1.0 + np.log1p(abs(r.hg - r.ag))) * (actual - expected)
            rating[r.home], rating[r.away] = rh + delta, ra - delta
    return pd.DataFrame(rows, columns=["season_idx", "fixture", "elo_home", "elo_away"])


def _allowed_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Points an opponent concedes to a position: mean points of opposing players of that position who played
    60+ minutes, rolled over the opponent's previous ``ALLOWED_WINDOW`` gameweeks. Keys: opp, position,
    season_idx, round.
    """
    played = df[df["played"] & (df["minutes"] >= 60)]
    got = played.groupby(["opp", "position", "season_idx", "round"], sort=False)["total_points"].mean().rename("pts").reset_index()
    keys = df[["opp", "position", "season_idx", "round"]].drop_duplicates()
    al = keys.merge(got, on=["opp", "position", "season_idx", "round"], how="left")
    al["t"] = al["season_idx"] * 100 + al["round"]
    al = al.sort_values(["opp", "position", "t"]).reset_index(drop=True)
    g = al.groupby(["opp", "position"], sort=False)["pts"]
    al["opp_allowed_pts"] = g.transform(lambda s: s.shift(1).rolling(ALLOWED_WINDOW, min_periods=3).mean())
    return al[["opp", "position", "season_idx", "round", "opp_allowed_pts"]]


def _heuristic_xp(f: pd.DataFrame) -> pd.Series:
    """Hand-built expected points: minutes x per-90 rates x fixture. Also the benchmark the ML model must beat."""
    m = (f["mins_avg_5"].clip(0, 90) / 90.0).fillna(0.0)
    p60 = f["p60_5"].fillna(0.0)
    pany = f["pany_5"].fillna(0.0)
    pos = f["position"]
    lam_against = (f["team_xga_6"] + f["opp_xgf_6"]) / 2.0 * np.where(f["was_home"], 0.92, 1.08)
    p_cs = np.exp(-lam_against)
    goal_pts = pos.map(GOAL_PTS)
    cs_pts = pos.map(CS_PTS)
    xp = (
        pany + p60
        + goal_pts * f["xg90_10"].fillna(0.0) * m
        + 3.0 * f["xa90_10"].fillna(0.0) * m
        + cs_pts * p_cs * p60
        + np.where(pos == 1, f["saves90_10"].fillna(0.0) / 3.0 * m, 0.0)
        + f["bonus90_10"].fillna(0.0) * m
        - np.where(pos <= 2, 0.5 * lam_against * p60, 0.0)
        - f["yc90_10"].fillna(0.0) * m
    )
    return pd.Series(xp, index=f.index)



def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Returns ``df`` (sorted, reindexed) plus feature columns. Works on played and future rows alike."""
    df = df.copy()
    df["_rank_t"] = df["season_idx"] * 100 + df["round"]
    df = df.sort_values(["_rank_t", "kickoff", "fixture", "name"]).reset_index(drop=True)
    df["played_any"] = (df["minutes"] > 0).astype(float).where(df["minutes"].notna())
    df["played60"] = (df["minutes"] >= 60).astype(float).where(df["minutes"].notna())

    pf = _player_round_features(df)
    tf = _team_round_features(df)
    out = df.merge(pf, on=["name", "season_idx", "round"], how="left")
    out = out.merge(tf, on=["team", "season_idx", "round"], how="left")
    own_ven = _venue_team_features(df)
    out = out.merge(own_ven, on=["team", "was_home", "season_idx", "round"], how="left")
    opp_ven = own_ven.rename(columns={"team": "opp", "was_home": "opp_home", **{c: c.replace("ven_", "oppven_") for c in own_ven.columns if c.startswith("ven_")}})
    out["opp_home"] = ~out["was_home"].astype(bool)
    out = out.merge(opp_ven, on=["opp", "opp_home", "season_idx", "round"], how="left")
    elo = _elo_features(df)
    out = out.merge(elo, on=["season_idx", "fixture"], how="left")
    out["elo_team"] = np.where(out["was_home"], out["elo_home"], out["elo_away"])
    out["elo_opp"] = np.where(out["was_home"], out["elo_away"], out["elo_home"])
    out["elo_diff"] = out["elo_team"] - out["elo_opp"] + np.where(out["was_home"], ELO_HOME_ADV, -ELO_HOME_ADV)
    out = out.drop(columns=["elo_home", "elo_away"])
    out = out.merge(_allowed_features(df), on=["opp", "position", "season_idx", "round"], how="left")
    opp_tf = tf.rename(columns={c: c.replace("team_", "opp_") for c in tf.columns if c.startswith("team_")})
    opp_tf = opp_tf.rename(columns={"team": "opp"})
    out = out.merge(opp_tf, on=["opp", "season_idx", "round"], how="left")
    for c in [c for c in out.columns if c.startswith("opp_") and c.endswith(("_6", "_15"))]:
        out[c] = out[c].fillna(LEAGUE_GOALS)
    for c in [c for c in out.columns if c.startswith("team_") and c.endswith(("_6", "_15"))]:
        out[c] = out[c].fillna(LEAGUE_GOALS)

    out["is_home"] = out["was_home"].astype(float)
    out["heuristic_xp"] = _heuristic_xp(out)
    out["lam_against"] = (out["team_xga_6"] + out["opp_xgf_6"]) / 2.0
    out["lam_for"] = (out["team_xgf_6"] + out["opp_xga_6"]) / 2.0
    out["strength_diff"] = (out["team_xgf_15"] - out["team_xga_15"]) - (out["opp_xgf_15"] - out["opp_xga_15"])
    return out.drop(columns=["_rank_t"])


def _feature_columns(sample_cols) -> List[str]:
    base = ["position", "value", "is_home", "fdr", "n_fix", "rounds_known", "heuristic_xp", "lam_against",
            "lam_for", "strength_diff", "lag1_minutes", "lag2_minutes", "lag1_points"]
    derived = [c for c in sample_cols if c.startswith((
        "mins_avg_", "start_rate_", "pts_avg_", "p60_", "pany_", "xg90_", "xa90_", "bonus90_", "bps90_",
        "ict90_", "saves90_", "dc90_", "xgc90_", "goals90_", "assists90_", "yc90_", "pts90_", "cs_per60_",
        "team_gf_", "team_ga_", "team_xgf_", "team_xga_", "opp_gf_", "opp_ga_", "opp_xgf_", "opp_xga_",
        "team_ppg_", "opp_ppg_", "ven_", "oppven_", "elo_", "opp_allowed_", "ewm_",
    ))]
    return base + derived


def feature_columns(df: pd.DataFrame, exclude_prefixes: Tuple[str, ...] = ()) -> List[str]:
    """Model inputs; ``exclude_prefixes`` drops whole feature groups (used for ablation tests)."""
    return [c for c in _feature_columns(df.columns) if not c.startswith(exclude_prefixes)]
