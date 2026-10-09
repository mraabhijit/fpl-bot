"""
Historical player/fixture data: vaastav dataset for past seasons, FPL API for the current one.

Every loader returns a fixture-level DataFrame (one row per player per fixture) with the
columns in ``COLUMNS``. Rows for fixtures that have not been played yet have ``played=False``
and NaN stats; they are what the model predicts.
"""

from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterable, List

import httpx
import numpy as np
import pandas as pd

from fpl_bot.core.config import DATA_DIR

CACHE_DIR = DATA_DIR / "cache"
VAASTAV_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
PAST_SEASONS = ["2022-23", "2023-24", "2024-25", "2025-26"]
POSITION_MAP = {"GK": 1, "GKP": 1, "DEF": 2, "MID": 3, "FWD": 4}

STAT_COLUMNS = [
    "minutes", "starts", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "bonus", "bps", "saves", "xg", "xa", "xgc", "ict",
    "defensive_contribution", "yellow_cards", "red_cards", "own_goals", "penalties_missed",
]
COLUMNS = [
    "season", "season_idx", "name", "position", "team", "opp", "round", "fixture",
    "was_home", "kickoff", "value", "team_goals", "opp_goals", "ep", "played",
] + STAT_COLUMNS


def season_index(season: str) -> int:
    """'2024-25' or '2024/25' -> 2024."""
    return int(season[:4])


def _fetch(url: str, cache_path: Path, refresh: bool) -> str:
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    resp = httpx.get(url, timeout=60.0, follow_redirects=True)
    resp.raise_for_status()
    cache_path.write_text(resp.text, encoding="utf-8")
    return resp.text


def load_vaastav_season(season: str, refresh: bool = False) -> pd.DataFrame:
    """One past season from vaastav/Fantasy-Premier-League, normalised to ``COLUMNS``."""
    base = f"{VAASTAV_URL}/{season}"
    gws = pd.read_csv(StringIO(_fetch(f"{base}/gws/merged_gw.csv", CACHE_DIR / f"{season}_merged_gw.csv", refresh)))
    teams = pd.read_csv(StringIO(_fetch(f"{base}/teams.csv", CACHE_DIR / f"{season}_teams.csv", refresh)))
    team_names = dict(zip(teams["id"], teams["name"]))

    was_home = gws["was_home"].astype(str).str.lower().eq("true")
    out = pd.DataFrame({
        "season": season,
        "season_idx": season_index(season),
        "name": gws["name"],
        "position": gws["position"].map(POSITION_MAP),
        "team": gws["team"],
        "opp": gws["opponent_team"].map(team_names),
        "round": gws["round"],
        "fixture": gws["fixture"],
        "was_home": was_home,
        "kickoff": pd.to_datetime(gws["kickoff_time"], utc=True, errors="coerce"),
        "value": gws["value"],
        "team_goals": np.where(was_home, gws["team_h_score"], gws["team_a_score"]),
        "opp_goals": np.where(was_home, gws["team_a_score"], gws["team_h_score"]),
        "ep": gws["xP"],
        "played": True,
        "minutes": gws["minutes"],
        "starts": gws["starts"],
        "total_points": gws["total_points"],
        "goals_scored": gws["goals_scored"],
        "assists": gws["assists"],
        "clean_sheets": gws["clean_sheets"],
        "goals_conceded": gws["goals_conceded"],
        "bonus": gws["bonus"],
        "bps": gws["bps"],
        "saves": gws["saves"],
        "xg": gws["expected_goals"],
        "xa": gws["expected_assists"],
        "xgc": gws["expected_goals_conceded"],
        "ict": gws["ict_index"],
        "defensive_contribution": gws["defensive_contribution"] if "defensive_contribution" in gws else 0,
        "yellow_cards": gws["yellow_cards"],
        "red_cards": gws["red_cards"],
        "own_goals": gws["own_goals"],
        "penalties_missed": gws["penalties_missed"],
    })
    return out[COLUMNS].dropna(subset=["position"]).astype({"position": int})  # drops AM (manager) rows


def load_past_seasons(seasons: Iterable[str] = PAST_SEASONS, refresh: bool = False) -> pd.DataFrame:
    frames = [load_vaastav_season(s, refresh) for s in seasons]
    return pd.concat(frames, ignore_index=True)


def _live_stat(stats: Dict[str, Any], key: str) -> float:
    try:
        return float(stats.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def load_current_season(
    bootstrap: Dict[str, Any],
    fixtures: List[Dict[str, Any]],
    live_by_gw: Dict[int, Dict[str, Any]],
    season: str,
) -> pd.DataFrame:
    """
    Current season rows from FPL API payloads.

    ``bootstrap`` is bootstrap-static, ``fixtures`` the full fixtures list and ``live_by_gw`` maps
    every finished gameweek to its ``event/{gw}/live`` payload. One row is produced per player per
    fixture (finished fixtures carry stats, the rest are prediction targets with NaN stats).
    Players without an ``explain`` entry in a finished fixture are recorded with 0 minutes.
    """
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    elements = {e["id"]: e for e in bootstrap["elements"]}
    fx_by_id = {f["id"]: f for f in fixtures if f.get("event")}
    players_by_team: Dict[int, List[Dict[str, Any]]] = {}
    for e in elements.values():
        players_by_team.setdefault(e["team"], []).append(e)

    # Per-fixture stats from the live payloads (explain holds per-fixture point breakdowns).
    played: Dict[tuple, Dict[str, float]] = {}
    for gw, live in live_by_gw.items():
        for item in live.get("elements", []):
            pid = item["id"]
            stats = item.get("stats", {})
            explains = item.get("explain", [])
            if not explains:
                continue
            for ex in explains:
                fx_id = ex["fixture"]
                row = {"total_points": float(sum(s["points"] for s in ex["stats"]))}
                for s in ex["stats"]:
                    row[s["identifier"]] = float(s["value"])
                if len(explains) == 1:
                    # Single fixture: the aggregate stats are exact (includes xG/xA/bps/ict).
                    for k in ("expected_goals", "expected_assists", "expected_goals_conceded", "ict_index", "bps", "starts"):
                        row[k] = _live_stat(stats, k)
                    row["minutes"] = _live_stat(stats, "minutes")
                played[(pid, fx_id)] = row

    rows = []
    for fx in fx_by_id.values():
        finished = bool(fx.get("finished") or fx.get("finished_provisional"))
        for side, tid, oid in (("h", fx["team_h"], fx["team_a"]), ("a", fx["team_a"], fx["team_h"])):
            was_home = side == "h"
            tg = fx.get("team_h_score") if was_home else fx.get("team_a_score")
            og = fx.get("team_a_score") if was_home else fx.get("team_h_score")
            for e in players_by_team.get(tid, []):
                stat = played.get((e["id"], fx["id"]))
                if not finished:
                    obs = None
                else:
                    # Finished fixture but no explain entry => player did not feature at all.
                    obs = stat or {"minutes": 0.0, "total_points": 0.0}
                rows.append({
                    "season": season,
                    "season_idx": season_index(season),
                    "name": f"{e['first_name']} {e['second_name']}",
                    "position": e["element_type"],
                    "team": teams[tid],
                    "opp": teams[oid],
                    "round": fx["event"],
                    "fixture": fx["id"],
                    "was_home": was_home,
                    "kickoff": pd.to_datetime(fx.get("kickoff_time"), utc=True, errors="coerce"),
                    "value": e["now_cost"],
                    "team_goals": tg if finished else np.nan,
                    "opp_goals": og if finished else np.nan,
                    "ep": np.nan,
                    "played": obs is not None,
                    "minutes": obs.get("minutes", 0.0) if obs else np.nan,
                    "starts": obs.get("starts", float(obs.get("minutes", 0) > 0)) if obs else np.nan,
                    "total_points": obs.get("total_points", 0.0) if obs else np.nan,
                    "goals_scored": obs.get("goals_scored", 0.0) if obs else np.nan,
                    "assists": obs.get("assists", 0.0) if obs else np.nan,
                    "clean_sheets": obs.get("clean_sheets", 0.0) if obs else np.nan,
                    "goals_conceded": obs.get("goals_conceded", 0.0) if obs else np.nan,
                    "bonus": obs.get("bonus", 0.0) if obs else np.nan,
                    "bps": obs.get("bps", 0.0) if obs else np.nan,
                    "saves": obs.get("saves", 0.0) if obs else np.nan,
                    "xg": obs.get("expected_goals", 0.0) if obs else np.nan,
                    "xa": obs.get("expected_assists", 0.0) if obs else np.nan,
                    "xgc": obs.get("expected_goals_conceded", 0.0) if obs else np.nan,
                    "ict": obs.get("ict_index", 0.0) if obs else np.nan,
                    "defensive_contribution": obs.get("defensive_contribution", 0.0) if obs else np.nan,
                    "yellow_cards": obs.get("yellow_cards", 0.0) if obs else np.nan,
                    "red_cards": obs.get("red_cards", 0.0) if obs else np.nan,
                    "own_goals": obs.get("own_goals", 0.0) if obs else np.nan,
                    "penalties_missed": obs.get("penalties_missed", 0.0) if obs else np.nan,
                })
    return pd.DataFrame(rows, columns=COLUMNS)
