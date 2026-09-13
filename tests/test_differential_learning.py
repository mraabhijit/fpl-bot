"""
Unit and integration tests for adaptive differential learning model optimizer.
Tests gameweek settlement, residual math, Empirical Bayes shrinkage,
Multi-Factor Ridge regression (team form, player form, elite consensus),
and projection calibration.
"""

import pytest
from fpl_bot.core.database import db
from fpl_bot.services.settlement_service import settlement_service
from fpl_bot.services.differential_trainer import differential_trainer, DifferentialTrainer
from fpl_bot.services.consensus_service import consensus_service
from fpl_bot.services.team_form_service import team_form_service
from fpl_bot.agents.projection_agent import projection_agent
from fpl_bot.core.models import Player, FixtureScore, PlayerAvailability
from fpl_bot.cli import run_retrain, run_differentials


def test_settle_gameweek_computes_residuals():
    summary = settlement_service.settle_gameweek(gameweek=4)
    assert summary["gameweek"] == 4
    assert summary["settled_count"] > 0
    assert summary["active_evaluated_count"] > 0
    assert summary["mae"] >= 0.0
    assert len(summary["top_positive_residuals"]) > 0
    assert len(summary["top_negative_residuals"]) > 0

    diffs = db.get_gameweek_differentials(gameweek=4)
    assert len(diffs) > 0
    first = diffs[0]
    assert "player_id" in first
    assert "residual" in first
    assert "actual_points" in first
    assert "projected_points" in first


def test_consensus_service_signals():
    consensus = consensus_service.get_elite_consensus(top_n=5)
    assert "sample_size" in consensus
    assert "elite_ownership" in consensus
    assert "elite_captains" in consensus
    assert "market_momentum" in consensus
    assert isinstance(consensus["elite_ownership"], dict)

    signal = consensus_service.get_player_consensus_signal(player_id=1)
    assert "elite_ownership" in signal
    assert "elite_captaincy" in signal
    assert "transfer_momentum" in signal
    assert 0.0 <= signal["elite_ownership"] <= 1.0


def test_team_form_service_metrics():
    team_metrics = team_form_service.get_all_team_form_metrics(window_size=3)
    assert len(team_metrics) == 20
    t1 = team_metrics[1]
    assert "goals_scored_rolling" in t1
    assert "goals_conceded_rolling" in t1
    assert "attack_momentum_index" in t1
    assert "defense_fragility_index" in t1

    matchup = team_form_service.get_team_matchup_metrics(team_id=1, opponent_team_id=2)
    assert "attacking_matchup" in matchup
    assert "clean_sheet_advantage" in matchup


def test_differential_trainer_multi_factor_ridge_and_clamping():
    trainer = DifferentialTrainer(shrinkage_lambda=3.0, max_delta=2.0, ridge_alpha=15.0)
    metrics = trainer.train(up_to_gw=4)

    assert metrics["trained_after_gw"] == 4
    assert metrics["algorithm"] == "multi_factor_ridge_regression"
    assert metrics["sample_count"] > 0
    assert metrics["players_modeled"] > 0
    assert metrics["mae"] > 0.0
    assert metrics["rmse"] > 0.0
    assert "feature_weights" in metrics

    fw = metrics["feature_weights"]
    for expected_feature in [
        "intercept",
        "prior_residual",
        "form_efficiency",
        "team_attack_momentum",
        "elite_consensus_ownership",
        "market_transfer_momentum",
    ]:
        assert expected_feature in fw

    # Verify predictions are bounded in [-2.0, +2.0]
    dummy_player = Player(
        id=1,
        web_name="Raya",
        first_name="David",
        second_name="Raya",
        team_id=1,
        team_short_name="ARS",
        element_type=1,
        position_name="GKP",
        now_cost=60,
        minutes=360,
        total_points=25,
        form=6.0,
        points_per_game=5.5,
        bps=70,
        selected_by_percent=25.0
    )

    for pid in [1, 2, 3, 10, 50, 100, 350, 426]:
        adj_simple = trainer.predict_adjustment(pid)
        assert -2.0 <= adj_simple <= 2.0

        adj_multi = trainer.predict_adjustment(
            player_id=pid,
            element_type=1,
            team_short_name="ARS",
            player=dummy_player
        )
        assert -2.0 <= adj_multi <= 2.0


def test_projection_agent_incorporates_calibrated_delta():
    dummy_player = Player(
        id=1,
        web_name="Raya",
        first_name="David",
        second_name="Raya",
        team_id=1,
        team_short_name="ARS",
        element_type=1,
        position_name="GKP",
        now_cost=60,
        minutes=360,
        total_points=25,
        form=6.0,
        bps=70,
        selected_by_percent=25.0
    )
    f_score = FixtureScore(
        team_id=1,
        fixture_score_1gw=4.0,
        fixture_score_3gw=3.5,
        fixture_score_5gw=3.2,
        fixture_score_8gw=3.0
    )
    avail = PlayerAvailability(
        player_id=1,
        availability_probability=1.0,
        start_probability=1.0,
        minutes_probability=1.0,
        rotation_risk=0.0,
        injury_risk=0.0
    )

    proj = projection_agent.generate_player_projection(
        player=dummy_player,
        target_gameweek=5,
        fixture_score=f_score,
        availability=avail
    )

    assert proj.player_id == 1
    assert proj.expected_fpl_points > 0.0
    assert proj.base_expected_fpl_points > 0.0
    assert isinstance(proj.calibration_delta, float)
    # Calibrated points should equal base + delta (bounded)
    assert proj.expected_fpl_points == round(max(0.5, proj.base_expected_fpl_points + proj.calibration_delta), 2)


def test_differentials_summary_structure():
    summary = differential_trainer.get_differentials_summary(gameweek=4)
    assert "feature_weights" in summary
    assert "elite_consensus" in summary
    assert "team_form_leaders" in summary
    assert "top_positive" in summary
    assert "top_negative" in summary
    assert "position_average_residuals" in summary


def test_cli_retrain_and_differentials():
    # Verify CLI functions execute without exception
    run_retrain(gameweek=4)
    run_differentials(gameweek=4)
