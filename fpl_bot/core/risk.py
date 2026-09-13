"""
Risk analysis and differential calculations for players, captains, and squads.
"""

from typing import Dict, List, Tuple
from fpl_bot.core.models import Player, PlayerAvailability


class RiskEngine:
    @staticmethod
    def calculate_captaincy_metrics(
        player: Player,
        base_xp: float,
        is_home: bool
    ) -> Dict[str, float]:
        """
        Computes captaincy metrics: expected points, floor, ceiling, differential impact.
        """
        # Ceiling: high threat, penalties, home match
        pen_order = player.penalties_order or 99
        has_penalties = (pen_order == 1)
        
        ceiling_mult = 2.2 if has_penalties else 1.8
        if is_home:
            ceiling_mult += 0.2

        floor_mult = 0.5
        if player.element_type in (1, 2):  # GKP/DEF can get negative or 1-2 pts easily
            floor_mult = 0.3

        ownership = player.selected_by_percent

        return {
            "captain_expected_points": round(base_xp * 2.0, 2),
            "captain_floor": round(base_xp * floor_mult, 1),
            "captain_ceiling": round(base_xp * ceiling_mult, 1),
            "ownership": ownership,
            "has_penalties": 1.0 if has_penalties else 0.0,
        }

    @staticmethod
    def calculate_differential_value(expected_points: float, ownership_percent: float) -> float:
        """
        Section 13:
        differential_value = expected_points * (1 - ownership_adjustment)
        Rewards high-expected-points players who are not template, without chasing low-quality punts.
        """
        # ownership in percent (0 to 100)
        # Low ownership (e.g. 5%) -> multiplier ~ 0.95
        # High ownership (e.g. 70%) -> multiplier ~ 0.30
        ownership_norm = min(1.0, max(0.0, ownership_percent / 100.0))
        return round(expected_points * (1.0 - 0.5 * ownership_norm), 2)

    @staticmethod
    def evaluate_squad_risk(players: List[Player], availabilities: Dict[int, PlayerAvailability]) -> Dict[str, float]:
        """
        Aggregates total squad injury and rotation risk.
        """
        total_injury_risk = 0.0
        total_rotation_risk = 0.0

        for p in players:
            avail = availabilities.get(p.id)
            if avail:
                total_injury_risk += avail.injury_risk
                total_rotation_risk += avail.rotation_risk
            else:
                if p.status in ("i", "s"):
                    total_injury_risk += 1.0
                elif p.status == "d":
                    total_injury_risk += 0.5

        return {
            "squad_injury_risk": round(total_injury_risk, 2),
            "squad_rotation_risk": round(total_rotation_risk, 2)
        }
