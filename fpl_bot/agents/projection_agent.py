"""
Projection Agent producing 1GW, 3GW, 5GW, and 8GW player projections.
Section 6 of FPL-Optimizer.md.
"""

from typing import Dict, List, Optional
from fpl_bot.core.models import Player, PlayerProjection, PlayerAvailability, FixtureScore
from fpl_bot.core.scoring import ScoringEngine


class ProjectionAgent:
    def __init__(self):
        self.scoring = ScoringEngine()

    def generate_player_projection(
        self,
        player: Player,
        target_gameweek: int,
        fixture_score: FixtureScore,
        availability: Optional[PlayerAvailability] = None
    ) -> PlayerProjection:
        """
        Generates comprehensive point projections across 1, 3, 5, 8 GW horizons.
        """
        avail_prob = availability.availability_probability if availability else 1.0
        start_prob = availability.start_probability if availability else 0.9
        min_prob = availability.minutes_probability if availability else 0.9

        # Calculate expected minutes per match
        if player.minutes > 0:
            avg_mins = min(90.0, player.minutes / max(1.0, (target_gameweek - 1)))
        else:
            avg_mins = 60.0 if start_prob > 0.6 else 20.0
        expected_minutes = round(avg_mins * min_prob, 1)

        # Expected goals & assists per match
        xg_per_90 = (player.expected_goals / max(1.0, player.minutes / 90.0)) if player.minutes > 90 else 0.1
        xa_per_90 = (player.expected_assists / max(1.0, player.minutes / 90.0)) if player.minutes > 90 else 0.08
        match_fraction = expected_minutes / 90.0

        expected_goals = round(xg_per_90 * match_fraction, 2)
        expected_assists = round(xa_per_90 * match_fraction, 2)

        # Clean sheet probability based on fixture score (score 1 to 5)
        cs_prob = 0.0
        if player.element_type in (1, 2):  # GKP, DEF
            cs_prob = round(0.20 + (fixture_score.fixture_score_1gw - 3.0) * 0.10, 2)
            cs_prob = max(0.05, min(0.65, cs_prob))
        elif player.element_type == 3:  # MID
            cs_prob = round(0.15 + (fixture_score.fixture_score_1gw - 3.0) * 0.05, 2)
            cs_prob = max(0.05, min(0.50, cs_prob))

        # Expected bonus points based on ICT index & BPS
        expected_bonus = round(min(1.5, max(0.0, (player.bps / max(1.0, (target_gameweek - 1))) * 0.05)), 2)

        # Expected cards
        expected_cards = 0.15 if player.element_type in (2, 3) else 0.05

        # Expected goals conceded
        expected_gc = round(max(0.4, 2.5 - (fixture_score.fixture_score_1gw * 0.4)), 2)

        # Set piece & penalty probabilities
        pen_order = player.penalties_order or 99
        set_order = player.direct_freekicks_order or 99
        expected_penalty_prob = 0.85 if pen_order == 1 else (0.3 if pen_order == 2 else 0.0)
        expected_set_piece_prob = 0.70 if set_order == 1 else (0.25 if set_order == 2 else 0.05)

        # Next Gameweek Expected Points
        # Use fixture_score_1gw inverted to difficulty: diff = 6.0 - fixture_score
        estimated_diff = max(1.0, min(5.0, 6.0 - fixture_score.fixture_score_1gw))
        xp_1gw = self.scoring.calculate_player_expected_points(
            player=player,
            fixture_difficulty=estimated_diff,
            is_home=True,  # Average or blended
            availability=availability
        )

        # Multi-Gameweek Horizon Projections
        # Scale with horizon fixture scores
        xp_3gw = round(xp_1gw * 0.95 * (fixture_score.fixture_score_3gw / 3.0) * 3, 1)
        xp_5gw = round(xp_1gw * 0.90 * (fixture_score.fixture_score_5gw / 3.0) * 5, 1)
        xp_8gw = round(xp_1gw * 0.85 * (fixture_score.fixture_score_8gw / 3.0) * 8, 1)

        confidence = round(min(0.95, max(0.30, 0.50 + (player.minutes / 400.0) * 0.45)), 2)

        return PlayerProjection(
            player_id=player.id,
            expected_minutes=expected_minutes,
            expected_starts=round(start_prob, 2),
            expected_goals=expected_goals,
            expected_assists=expected_assists,
            expected_clean_sheet_probability=cs_prob,
            expected_bonus=expected_bonus,
            expected_cards=expected_cards,
            expected_goals_conceded=expected_gc,
            expected_penalty_probability=expected_penalty_prob,
            expected_set_piece_probability=expected_set_piece_prob,
            expected_fpl_points=xp_1gw,
            confidence=confidence,
            horizon_points={
                1: xp_1gw,
                3: xp_3gw,
                5: xp_5gw,
                8: xp_8gw,
            }
        )

    def generate_all_projections(
        self,
        players: List[Player],
        target_gameweek: int,
        fixture_scores: Dict[int, FixtureScore],
        availabilities: Dict[int, PlayerAvailability]
    ) -> Dict[int, PlayerProjection]:
        projections = {}
        for p in players:
            f_score = fixture_scores.get(p.team_id) or FixtureScore(
                team_id=p.team_id,
                fixture_score_1gw=3.0,
                fixture_score_3gw=3.0,
                fixture_score_5gw=3.0,
                fixture_score_8gw=3.0
            )
            avail = availabilities.get(p.id)
            projections[p.id] = self.generate_player_projection(p, target_gameweek, f_score, avail)
        return projections


projection_agent = ProjectionAgent()
