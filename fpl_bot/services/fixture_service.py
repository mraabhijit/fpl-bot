"""
Fixture analysis service calculating multi-gameweek difficulty, congestion, blanks, doubles, and swings.
Section 7 of FPL-Optimizer.md.
"""

from typing import Any, Dict, List, Optional
from fpl_bot.core.models import Fixture, FixtureScore, Team
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class FixtureService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self._fixtures_cache: Optional[List[Fixture]] = None

    def get_all_fixtures(self, force_refresh: bool = False) -> List[Fixture]:
        if self._fixtures_cache and not force_refresh:
            return self._fixtures_cache

        raw_fixtures = self.api.get_fixtures()
        fixtures: List[Fixture] = []
        for f in raw_fixtures:
            fixtures.append(Fixture(
                id=f["id"],
                event=f.get("event"),
                team_h=f["team_h"],
                team_a=f["team_a"],
                team_h_difficulty=f.get("team_h_difficulty", 3),
                team_a_difficulty=f.get("team_a_difficulty", 3),
                kickoff_time=f.get("kickoff_time"),
                finished=f.get("finished", False),
                started=f.get("started", False),
                team_h_score=f.get("team_h_score"),
                team_a_score=f.get("team_a_score"),
            ))
        self._fixtures_cache = fixtures
        return fixtures

    def get_team_fixtures_for_horizon(
        self,
        team_id: int,
        start_gameweek: int,
        horizon_gws: int
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all scheduled matches for a team over [start_gameweek, start_gameweek + horizon_gws - 1].
        Correctly accounts for Blank Gameweeks (0 matches) and Double Gameweeks (2+ matches).
        """
        fixtures = self.get_all_fixtures()
        target_gws = set(range(start_gameweek, start_gameweek + horizon_gws))
        
        matches = []
        for f in fixtures:
            if f.event in target_gws:
                if f.team_h == team_id:
                    matches.append({
                        "fixture_id": f.id,
                        "event": f.event,
                        "opponent_id": f.team_a,
                        "is_home": True,
                        "difficulty": f.team_h_difficulty,
                    })
                elif f.team_a == team_id:
                    matches.append({
                        "fixture_id": f.id,
                        "event": f.event,
                        "opponent_id": f.team_h,
                        "is_home": False,
                        "difficulty": f.team_a_difficulty,
                    })
        return sorted(matches, key=lambda m: (m["event"] or 99, not m["is_home"]))

    def compute_team_fixture_scores(
        self,
        team_id: int,
        current_gameweek: int
    ) -> FixtureScore:
        """
        Produces:
        fixture_score_1GW
        fixture_score_3GW
        fixture_score_5GW
        fixture_score_8GW
        Score higher is more favorable (scale 1.0 to 5.0, where 5.0 = easiest fixtures / doubles, 1.0 = hard / blank).
        """
        def score_for_horizon(horizon: int) -> float:
            matches = self.get_team_fixtures_for_horizon(team_id, current_gameweek, horizon)
            if not matches:
                # Blank gameweek! Very unfavourable
                return 1.0

            # Double gameweek gives extra fixture value
            total_score = 0.0
            for m in matches:
                # Base difficulty is 1 to 5. Favorable fixture is 6 - difficulty (e.g. diff 2 -> 4 pts).
                favorable_diff = 6.0 - m["difficulty"]
                # Home bonus
                if m["is_home"]:
                    favorable_diff += 0.5
                total_score += favorable_diff

            # Normalize by number of expected gameweeks
            normalized = total_score / horizon
            return round(min(5.0, max(1.0, normalized)), 2)

        return FixtureScore(
            team_id=team_id,
            fixture_score_1gw=score_for_horizon(1),
            fixture_score_3gw=score_for_horizon(3),
            fixture_score_5gw=score_for_horizon(5),
            fixture_score_8gw=score_for_horizon(8),
        )


fixture_service = FixtureService()
