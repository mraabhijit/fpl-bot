import pytest
from fpl_bot.core.models import Player, PlayerAvailability
from fpl_bot.core.scoring import ScoringEngine
from fpl_bot.core.risk import RiskEngine


def test_scoring_engine_calculation():
    player = Player(
        id=100,
        web_name="Salah",
        first_name="Mohamed",
        second_name="Salah",
        team_id=14,
        element_type=3,  # MID
        now_cost=125,
        form=7.5,
        points_per_game=7.2,
        expected_goals=0.6,
        expected_assists=0.4,
        status="a"
    )

    xp_easy = ScoringEngine.calculate_player_expected_points(
        player=player,
        fixture_difficulty=2.0,  # Easy fixture
        is_home=True
    )

    xp_hard = ScoringEngine.calculate_player_expected_points(
        player=player,
        fixture_difficulty=5.0,  # Hard fixture
        is_home=False
    )

    # Easy home fixture should yield more expected points than hard away
    assert xp_easy > xp_hard
    assert xp_easy > 4.0


def test_hit_roi_evaluation():
    # Immediate gain of 1.0 pt + 3-GW gain of 1.0 pt -> Total projected = 1 + 0.5 = 1.5 < 4 + 2 -> False
    assert ScoringEngine.evaluate_hit_roi(immediate_gain=1.0, future_3gw_gain=1.0, hit_cost=4) is False
    # Significant gain: immediate 4.5 + future 8.0 -> 4.5 + 4.0 = 8.5 - 4 = 4.5 >= 2.0 -> True
    assert ScoringEngine.evaluate_hit_roi(immediate_gain=4.5, future_3gw_gain=8.0, hit_cost=4) is True
    # Minor gain should not trigger hit
    assert ScoringEngine.evaluate_hit_roi(immediate_gain=1.0, future_3gw_gain=2.0, hit_cost=4) is False


def test_differential_value():
    diff_low_own = RiskEngine.calculate_differential_value(expected_points=6.0, ownership_percent=5.0)
    diff_high_own = RiskEngine.calculate_differential_value(expected_points=6.0, ownership_percent=70.0)

    # Low ownership gives higher differential multiplier
    assert diff_low_own > diff_high_own
