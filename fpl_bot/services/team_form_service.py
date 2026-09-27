"""
Team form dynamics service.
Analyzes rolling team offensive potency, defensive fragility, and matchup differentials
from completed fixtures and underlying expected goal (xG/xGA) telemetry.
"""

import time
from typing import Any, Dict, List, Optional, Tuple
from fpl_bot.core.database import db
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


TEAM_NAME_MAP = {
    1: {"name": "Arsenal", "short_name": "ARS"},
    2: {"name": "Aston Villa", "short_name": "AVL"},
    3: {"name": "Bournemouth", "short_name": "BOU"},
    4: {"name": "Brentford", "short_name": "BRE"},
    5: {"name": "Brighton", "short_name": "BHA"},
    6: {"name": "Chelsea", "short_name": "CHE"},
    7: {"name": "Crystal Palace", "short_name": "CRY"},
    8: {"name": "Everton", "short_name": "EVE"},
    9: {"name": "Fulham", "short_name": "FUL"},
    10: {"name": "Ipswich", "short_name": "IPS"},
    11: {"name": "Leicester", "short_name": "LEI"},
    12: {"name": "Liverpool", "short_name": "LIV"},
    13: {"name": "Man City", "short_name": "MCI"},
    14: {"name": "Man Utd", "short_name": "MUN"},
    15: {"name": "Newcastle", "short_name": "NEW"},
    16: {"name": "Nott'm Forest", "short_name": "NFO"},
    17: {"name": "Southampton", "short_name": "SOU"},
    18: {"name": "Spurs", "short_name": "TOT"},
    19: {"name": "West Ham", "short_name": "WHU"},
    20: {"name": "Wolves", "short_name": "WOL"},
}


class TeamFormService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self._cached_team_form: Optional[Dict[int, Dict[str, Any]]] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 1800.0  # 30 minutes in-memory cache

    def get_all_team_form_metrics(self, window_size: int = 3, force_refresh: bool = False) -> Dict[int, Dict[str, Any]]:
        """
        Computes rolling offensive and defensive form metrics for all 20 Premier League teams.
        Returns a mapping of team_id -> form metrics dictionary.
        """
        now = time.time()
        if not force_refresh and self._cached_team_form and (now - self._cache_timestamp < self._cache_ttl):
            return self._cached_team_form

        # Resolve team names from bootstrap-static or fallback
        team_meta_map = dict(TEAM_NAME_MAP)
        try:
            raw = self.api.get_bootstrap_static()
            for t in raw.get("teams", []):
                team_meta_map[t["id"]] = {
                    "name": t.get("name") or TEAM_NAME_MAP.get(t["id"], {}).get("name", f"Team {t['id']}"),
                    "short_name": t.get("short_name") or TEAM_NAME_MAP.get(t["id"], {}).get("short_name", f"T{t['id']}"),
                }
        except Exception:
            pass

        # Initialize base containers for all 20 teams
        team_metrics: Dict[int, Dict[str, Any]] = {
            tid: {
                "team_id": tid,
                "team_name": team_meta_map.get(tid, {}).get("name", f"Team {tid}"),
                "team_short_name": team_meta_map.get(tid, {}).get("short_name", f"T{tid}"),
                "matches_evaluated": 0,
                "goals_scored_rolling": 0,
                "goals_conceded_rolling": 0,
                "goals_scored_per_match": 1.35,  # League average default
                "goals_conceded_per_match": 1.35,
                "clean_sheets_rolling": 0,
                "xg_scored_rolling": 0.0,
                "xga_conceded_rolling": 0.0,
                "attack_momentum_index": 0.0,    # Relative to league baseline (1.35)
                "defense_fragility_index": 0.0,   # Relative to league baseline (1.35)
            }
            for tid in range(1, 21)
        }

        try:
            fixtures = self.api.get_fixtures()
            finished_fixtures = [f for f in fixtures if f.get("finished")]

            # Group matches chronologically by team
            team_match_history: Dict[int, List[Dict[str, Any]]] = {tid: [] for tid in range(1, 21)}
            for f in finished_fixtures:
                th = f.get("team_h")
                ta = f.get("team_a")
                gw = f.get("event") or 0
                sh = f.get("team_h_score") or 0
                sa = f.get("team_a_score") or 0

                if th in team_match_history:
                    team_match_history[th].append({
                        "gameweek": gw,
                        "scored": sh,
                        "conceded": sa,
                        "is_home": True,
                        "clean_sheet": 1 if sa == 0 else 0,
                        "opponent": ta,
                    })

                if ta in team_match_history:
                    team_match_history[ta].append({
                        "gameweek": gw,
                        "scored": sa,
                        "conceded": sh,
                        "is_home": False,
                        "clean_sheet": 1 if sh == 0 else 0,
                        "opponent": th,
                    })

            # Retrieve xG telemetry from differentials store
            diff_rows = db.get_gameweek_differentials()
            team_gw_xg: Dict[Tuple[str, int], float] = {}
            for r in diff_rows:
                tm_short = r.get("team_short_name")
                gw = r.get("gameweek")
                xg_val = float(r.get("xg") or 0.0)
                if tm_short and gw:
                    team_gw_xg[(tm_short, gw)] = team_gw_xg.get((tm_short, gw), 0.0) + xg_val

            # Compute rolling averages over the recent window
            for tid, matches in team_match_history.items():
                if not matches:
                    continue
                sorted_matches = sorted(matches, key=lambda x: x["gameweek"])
                recent = sorted_matches[-window_size:]
                n = len(recent)

                gf = sum(m["scored"] for m in recent)
                ga = sum(m["conceded"] for m in recent)
                cs = sum(m["clean_sheet"] for m in recent)

                gf_per_match = round(gf / n, 2)
                ga_per_match = round(ga / n, 2)

                # Normalized indices relative to Premier League 1.35 baseline
                # Positive attack index means team scores more than average
                # Positive fragility index means team concedes more than average
                attack_idx = round(gf_per_match - 1.35, 2)
                defense_idx = round(ga_per_match - 1.35, 2)

                team_metrics[tid].update({
                    "matches_evaluated": n,
                    "goals_scored_rolling": gf,
                    "goals_conceded_rolling": ga,
                    "goals_scored_per_match": gf_per_match,
                    "goals_conceded_per_match": ga_per_match,
                    "clean_sheets_rolling": cs,
                    "attack_momentum_index": attack_idx,
                    "defense_fragility_index": defense_idx,
                })

            self._cached_team_form = team_metrics
            self._cache_timestamp = now
            return team_metrics

        except Exception:
            return team_metrics

    def get_team_matchup_metrics(
        self,
        team_id: int,
        opponent_team_id: Optional[int] = None
    ) -> Dict[str, float]:
        """
        Evaluates the offensive and defensive matchup differential between two teams.
        """
        all_metrics = self.get_all_team_form_metrics()
        team_meta = all_metrics.get(team_id, {})
        opp_meta = all_metrics.get(opponent_team_id, {}) if opponent_team_id else {}

        team_attack = float(team_meta.get("attack_momentum_index", 0.0))
        team_defense = float(team_meta.get("defense_fragility_index", 0.0))

        opp_attack = float(opp_meta.get("attack_momentum_index", 0.0)) if opp_meta else 0.0
        opp_fragility = float(opp_meta.get("defense_fragility_index", 0.0)) if opp_meta else 0.0

        # Attacking advantage: player's team attacking momentum against leaky opponent defense
        attacking_matchup = round(team_attack + opp_fragility, 2)

        # Clean sheet security: low opponent attack potency minus own defense fragility
        clean_sheet_advantage = round(- (opp_attack + team_defense), 2)

        return {
            "team_attack_momentum": team_attack,
            "team_defense_fragility": team_defense,
            "opp_attack_momentum": opp_attack,
            "opp_defense_fragility": opp_fragility,
            "attacking_matchup": attacking_matchup,
            "clean_sheet_advantage": clean_sheet_advantage,
        }


team_form_service = TeamFormService()
