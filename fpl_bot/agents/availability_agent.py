"""
Availability Agent continuously evaluating injuries, suspensions, rotation risk, and late team news.
Section 8 of FPL-Optimizer.md.
"""

from typing import Dict, List, Optional
from fpl_bot.core.models import Player, PlayerAvailability
from fpl_bot.services.news_service import news_service, NewsService


class AvailabilityAgent:
    def __init__(self, service: Optional[NewsService] = None):
        self.service = service or news_service

    def evaluate_squad_availability(self, players: List[Player]) -> Dict[int, PlayerAvailability]:
        """
        Evaluates availability for each player in squad or transfer candidate pool.
        """
        return self.service.get_all_availabilities(players)


availability_agent = AvailabilityAgent()
