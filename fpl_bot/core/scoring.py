"""
Scoring and objective function calculation according to Section 14 and Section 10 of FPL-Optimizer.md.
"""

from typing import Dict, List, Optional
from fpl_bot.core.config import settings
from fpl_bot.core.models import Player, PlayerProjection, PlayerAvailability


class ScoringEngine:
    @staticmethod
    def calculate_player_expected_points(
        player: Player,
        fixture_difficulty: float,
        is_home: bool,
        availability: Optional[PlayerAvailability] = None
    ) -> float:
        """
        Calculates expected FPL points for a player for an upcoming match.
        Takes into account:
        - Recent form & points per game
        - Expected goal involvements (xG, xA)
        - Expected clean sheets (position-based)
        - Fixture difficulty adjustment
        - Home advantage (~10% boost for attack, ~15% for defence)
        - Availability / start probability
        """
        base_points = player.form if player.form > 0 else (player.points_per_game or 2.0)

        # Attack and involvement bonus
        xg_bonus = player.expected_goals * (5.0 if player.element_type == 3 else 4.0)
        xa_bonus = player.expected_assists * 3.0
        
        # Fixture multiplier: difficulty 1-5 (3 is neutral)
        # diff 1 => 1.25x, diff 2 => 1.15x, diff 3 => 1.0x, diff 4 => 0.85x, diff 5 => 0.70x
        diff_mult = max(0.6, 1.0 + (3.0 - fixture_difficulty) * 0.15)

        # Home advantage
        venue_mult = 1.10 if is_home else 0.95

        # Position specific clean sheet probability
        cs_factor = 0.0
        if player.element_type in (1, 2):  # GKP, DEF
            cs_factor = 4.0 * max(0.1, (5.0 - fixture_difficulty) / 10.0) * (1.15 if is_home else 0.9)
        elif player.element_type == 3:  # MID
            cs_factor = 1.0 * max(0.1, (5.0 - fixture_difficulty) / 10.0)

        raw_xp = (0.5 * base_points + 0.3 * (xg_bonus + xa_bonus) + cs_factor) * diff_mult * venue_mult

        # Apply availability probability
        avail_mult = 1.0
        if availability:
            avail_mult = availability.availability_probability * availability.minutes_probability
        elif player.chance_of_playing_next_round is not None:
            avail_mult = (player.chance_of_playing_next_round / 100.0)
        elif player.status in ("i", "s", "u"):
            avail_mult = 0.0
        elif player.status == "d":
            avail_mult = 0.5

        return round(max(0.0, raw_xp * avail_mult), 2)

    @staticmethod
    def calculate_utility(
        expected_points: float,
        rank_gain_value: float = 0.0,
        mini_league_gain_value: float = 0.0,
        future_squad_value: float = 0.0,
        flexibility_value: float = 0.0,
        hit_cost: float = 0.0,
        transfer_opportunity_cost: float = 0.0,
        rotation_risk_penalty: float = 0.0,
        injury_risk_penalty: float = 0.0
    ) -> float:
        """
        Evaluates Section 14 UTILITY function:
        UTILITY = expected_points + rank_gain_value + mini_league_gain_value
                  + future_squad_value + flexibility_value - hit_cost
                  - transfer_opportunity_cost - rotation_risk_penalty - injury_risk_penalty
        """
        utility = (
            expected_points * settings.short_term_points_weight
            + rank_gain_value * settings.overall_rank_weight
            + mini_league_gain_value * settings.mini_league_weight
            + future_squad_value * settings.long_term_points_weight
            + flexibility_value
            - hit_cost * settings.hit_penalty_cost
            - transfer_opportunity_cost
            - rotation_risk_penalty
            - injury_risk_penalty
        )
        return round(utility, 3)

    @staticmethod
    def evaluate_hit_roi(
        immediate_gain: float,
        future_3gw_gain: float,
        hit_cost: int = 4
    ) -> bool:
        """
        Evaluates Section 10 hit justification:
        Net gain must exceed the hit cost plus threshold over short-to-medium horizon.
        """
        total_projected_gain = immediate_gain + (0.5 * future_3gw_gain)
        return (total_projected_gain - hit_cost) >= settings.hit_minimum_gain_threshold
