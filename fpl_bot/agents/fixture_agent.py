"""
Fixture Agent calculating team fixture strengths across 1, 3, 5, and 8 GW horizons.
Section 7 of FPL-Optimizer.md.
"""

from typing import Dict, List, Optional
from fpl_bot.core.models import FixtureScore, Team
from fpl_bot.services.fixture_service import fixture_service, FixtureService


class FixtureAgent:
    def __init__(self, service: Optional[FixtureService] = None):
        self.service = service or fixture_service

    def analyze_all_teams(self, teams: List[Team], current_gameweek: int) -> Dict[int, FixtureScore]:
        scores = {}
        for t in teams:
            scores[t.id] = self.service.compute_team_fixture_scores(t.id, current_gameweek)
        return scores


fixture_agent = FixtureAgent()
