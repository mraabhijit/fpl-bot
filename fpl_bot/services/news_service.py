"""
News and availability service synthesizing injuries, suspensions, and manager updates.
Section 8 of FPL-Optimizer.md.
"""

from typing import Dict, List, Optional
from fpl_bot.core.models import Player, PlayerAvailability


class NewsService:
    @staticmethod
    def evaluate_player_availability(player: Player) -> PlayerAvailability:
        """
        Parses official FPL news, status tags, and chance of playing.
        Produces:
        - availability_probability
        - start_probability
        - minutes_probability
        - rotation_risk
        - injury_risk
        """
        news = player.news or ""
        status = player.status  # a: available, d: doubtful, i: injured, s: suspended, u: unavailable

        # Base probabilities
        if status in ("i", "s", "u"):
            avail_prob = 0.0
            start_prob = 0.0
            min_prob = 0.0
            inj_risk = 1.0 if status == "i" else 0.0
            rot_risk = 0.0
        elif status == "d":
            # Doubtful: check chance of playing
            cop = player.chance_of_playing_next_round
            if cop is not None:
                avail_prob = cop / 100.0
            else:
                avail_prob = 0.5
            start_prob = avail_prob * 0.85
            min_prob = avail_prob * 0.80
            inj_risk = 1.0 - avail_prob
            rot_risk = 0.3
        else:
            # Available ('a')
            avail_prob = 1.0
            inj_risk = 0.05
            # Estimate start probability based on minutes played and appearances
            if player.minutes > 200:
                start_prob = 0.92
                min_prob = 0.90
                rot_risk = 0.10
            elif player.minutes > 90:
                start_prob = 0.75
                min_prob = 0.70
                rot_risk = 0.30
            else:
                start_prob = 0.40
                min_prob = 0.35
                rot_risk = 0.60

        # Adjust for key words in news
        lower_news = news.lower()
        if "knock" in lower_news or "muscle" in lower_news or "hamstring" in lower_news:
            inj_risk = max(inj_risk, 0.4)
            start_prob *= 0.8
        if "illness" in lower_news:
            inj_risk = max(inj_risk, 0.3)
        if "ban" in lower_news or "suspended" in lower_news:
            avail_prob = 0.0
            start_prob = 0.0
            min_prob = 0.0

        return PlayerAvailability(
            player_id=player.id,
            availability_probability=round(avail_prob, 2),
            start_probability=round(start_prob, 2),
            minutes_probability=round(min_prob, 2),
            rotation_risk=round(rot_risk, 2),
            injury_risk=round(inj_risk, 2),
            news=news,
        )

    def get_all_availabilities(self, players: List[Player]) -> Dict[int, PlayerAvailability]:
        return {p.id: self.evaluate_player_availability(p) for p in players}


news_service = NewsService()
