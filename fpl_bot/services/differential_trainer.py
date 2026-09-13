"""
Adaptive Differential Learning Trainer.
Trains online regularized error-correction models using weekly gameweek differentials.
Applies Empirical Bayes shrinkage and Ridge regularization to isolate systematic bias
from random matchday noise, producing calibrated player projection adjustments.
"""

import math
from typing import Any, Dict, List, Optional, Tuple
from fpl_bot.core.database import db


class DifferentialTrainer:
    def __init__(self, shrinkage_lambda: float = 3.0, max_delta: float = 2.0):
        self.shrinkage_lambda = shrinkage_lambda  # Controls shrinkage toward group mean for small samples
        self.max_delta = max_delta                # Maximum adjustment ceiling [-max_delta, +max_delta]
        self._cached_weights: Optional[Dict[str, Any]] = None

    def train(self, up_to_gw: Optional[int] = None) -> Dict[str, Any]:
        """
        Trains an adaptive error-correction model on all differentials up to the specified gameweek.
        Returns training metrics and saves checkpoint to SQLite.
        """
        rows = db.get_gameweek_differentials()
        if up_to_gw is not None:
            rows = [r for r in rows if r["gameweek"] <= up_to_gw]

        if not rows:
            return {
                "trained_after_gw": up_to_gw or 0,
                "status": "NO_DATA",
                "sample_count": 0,
                "mae": 0.0,
                "rmse": 0.0,
            }

        target_gw = up_to_gw or max(r["gameweek"] for r in rows)

        # 1. Aggregate statistics by Player, Position, and Team
        player_stats: Dict[int, Dict[str, Any]] = {}
        pos_stats: Dict[int, List[float]] = {1: [], 2: [], 3: [], 4: []}
        team_stats: Dict[str, List[float]] = {}

        for r in rows:
            pid = r["player_id"]
            p_pos = r["element_type"]
            team = r["team_short_name"]
            res = float(r["residual"])

            # Position level residuals
            if p_pos in pos_stats:
                pos_stats[p_pos].append(res)

            # Team level residuals
            if team:
                if team not in team_stats:
                    team_stats[team] = []
                team_stats[team].append(res)

            # Player level aggregation
            if pid not in player_stats:
                player_stats[pid] = {
                    "player_name": r["player_name"],
                    "element_type": p_pos,
                    "team": team,
                    "residuals": [],
                    "minutes_residuals": [],
                    "xgi_deltas": [],
                }

            player_stats[pid]["residuals"].append(res)
            player_stats[pid]["minutes_residuals"].append(float(r["minutes_residual"]))
            
            # Goal involvement efficiency: (actual goals + assists) - (xG + xA)
            act_gi = float(r["actual_goals"]) + float(r["actual_assists"])
            exp_gi = float(r["xg"]) + float(r["xa"])
            player_stats[pid]["xgi_deltas"].append(act_gi - exp_gi)

        # 2. Compute Global, Positional, and Team-Level Means
        global_mean = sum(r["residual"] for r in rows) / len(rows)
        pos_means = {
            pos: (sum(res_list) / len(res_list)) if res_list else global_mean
            for pos, res_list in pos_stats.items()
        }
        team_means = {
            tm: (sum(res_list) / len(res_list)) if res_list else global_mean
            for tm, res_list in team_stats.items()
        }

        # 3. Fit Empirical Bayes Shrinkage Estimators per Player
        player_adjustments: Dict[str, float] = {}
        total_sq_error = 0.0
        total_abs_error = 0.0

        for pid, pdata in player_stats.items():
            res_list = pdata["residuals"]
            n = len(res_list)
            player_avg_res = sum(res_list) / n

            # Shrinkage weight: w = n / (n + lambda)
            # More observations -> greater confidence in player-specific deviation
            w_player = n / (n + self.shrinkage_lambda)

            pos = pdata["element_type"]
            team = pdata["team"]
            pos_prior = pos_means.get(pos, 0.0)
            team_prior = team_means.get(team, 0.0)

            # Blended prior combining positional and team trends
            blended_prior = 0.6 * pos_prior + 0.4 * team_prior

            # Raw shrinkage prediction
            raw_delta = (w_player * player_avg_res) + ((1.0 - w_player) * blended_prior)

            # Additional efficiency nudge if player consistently outperforms underlying xG/xA
            avg_xgi_delta = sum(pdata["xgi_deltas"]) / n
            efficiency_nudge = max(-0.5, min(0.5, avg_xgi_delta * 0.2))

            combined_delta = raw_delta + efficiency_nudge

            # Strict guardrail: bound adjustment within [-max_delta, +max_delta]
            bounded_delta = max(-self.max_delta, min(self.max_delta, combined_delta))
            bounded_delta = round(bounded_delta, 2)

            player_adjustments[str(pid)] = bounded_delta

            # Track calibration metrics across observed sample
            for r in res_list:
                err = (r - bounded_delta)
                total_abs_error += abs(err)
                total_sq_error += err ** 2

        n_samples = len(rows)
        mae = round(total_abs_error / n_samples, 3)
        rmse = round(math.sqrt(total_sq_error / n_samples), 3)

        # Baseline variance to calculate R-squared
        baseline_sq_error = sum((r["residual"] - global_mean) ** 2 for r in rows)
        r2 = round(1.0 - (total_sq_error / max(1e-6, baseline_sq_error)), 3)

        checkpoint_payload = {
            "trained_after_gw": target_gw,
            "algorithm": "bayesian_ridge_shrinkage",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "sample_count": n_samples,
            "weights_json": {
                "player_adjustments": player_adjustments,
                "position_means": {str(k): round(v, 3) for k, v in pos_means.items()},
                "team_means": {str(k): round(v, 3) for k, v in team_means.items()},
                "global_mean": round(global_mean, 3),
                "shrinkage_lambda": self.shrinkage_lambda,
                "max_delta": self.max_delta,
            },
            "metrics_json": {
                "players_modeled": len(player_adjustments),
                "mae": mae,
                "rmse": rmse,
                "r2": r2,
                "gameweeks_covered": list(sorted(set(r["gameweek"] for r in rows))),
            }
        }

        chk_id = db.save_model_checkpoint(checkpoint_payload)
        self._cached_weights = checkpoint_payload["weights_json"]

        db.log_audit(
            gameweek=target_gw,
            event_type="MODEL_RETRAINED",
            details={
                "checkpoint_id": chk_id,
                "mae": mae,
                "rmse": rmse,
                "r2": r2,
                "players_count": len(player_adjustments),
            },
            result="SUCCESS"
        )

        return {
            "checkpoint_id": chk_id,
            "trained_after_gw": target_gw,
            "algorithm": "bayesian_ridge_shrinkage",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "sample_count": n_samples,
            "players_modeled": len(player_adjustments),
        }

    def predict_adjustment(
        self,
        player_id: int,
        element_type: int = 3,
        team_short_name: Optional[str] = None
    ) -> float:
        """
        Infers the calibrated additive adjustment hat_delta for a player's baseline projection.
        Guaranteed to be clamped in [-max_delta, +max_delta].
        """
        if self._cached_weights is None:
            latest = db.get_latest_model_checkpoint()
            if latest and isinstance(latest.get("weights_json"), dict):
                self._cached_weights = latest["weights_json"]
            else:
                return 0.0

        p_adjustments = self._cached_weights.get("player_adjustments", {})
        pid_str = str(player_id)
        if pid_str in p_adjustments:
            return float(p_adjustments[pid_str])

        # If individual player not yet in sample, fall back to blended position + team prior
        pos_means = self._cached_weights.get("position_means", {})
        team_means = self._cached_weights.get("team_means", {})
        pos_prior = float(pos_means.get(str(element_type), 0.0))
        team_prior = float(team_means.get(str(team_short_name), 0.0)) if team_short_name else 0.0

        fallback_delta = 0.6 * pos_prior + 0.4 * team_prior
        # Dampen prior for unobserved player by 50%
        dampened = fallback_delta * 0.5
        return round(max(-self.max_delta, min(self.max_delta, dampened)), 2)

    def get_differentials_summary(self, gameweek: Optional[int] = None) -> Dict[str, Any]:
        """
        Produces a rich structured summary of differentials, top overperformers,
        top underperformers, and model checkpoint metrics for UI and CLI display.
        """
        differentials = db.get_gameweek_differentials(gameweek=gameweek)
        latest_chk = db.get_latest_model_checkpoint()

        top_positive = sorted(differentials, key=lambda x: x["residual"], reverse=True)[:5]
        top_negative = sorted(differentials, key=lambda x: x["residual"])[:5]

        # Positional average residuals
        pos_res: Dict[str, List[float]] = {"GKP": [], "DEF": [], "MID": [], "FWD": []}
        for d in differentials:
            pos = d.get("position_name", "MID")
            if pos in pos_res:
                pos_res[pos].append(float(d["residual"]))

        pos_summary = {
            pos: round(sum(vals) / len(vals), 2) if vals else 0.0
            for pos, vals in pos_res.items()
        }

        return {
            "gameweek": gameweek or (differentials[0]["gameweek"] if differentials else 0),
            "sample_count": len(differentials),
            "latest_checkpoint": latest_chk,
            "position_average_residuals": pos_summary,
            "top_positive": [
                {
                    "player_id": d["player_id"],
                    "player_name": d["player_name"],
                    "team": d["team_short_name"],
                    "position": d["position_name"],
                    "actual_points": d["actual_points"],
                    "projected_points": d["projected_points"],
                    "residual": d["residual"],
                    "minutes": d["actual_minutes"],
                }
                for d in top_positive
            ],
            "top_negative": [
                {
                    "player_id": d["player_id"],
                    "player_name": d["player_name"],
                    "team": d["team_short_name"],
                    "position": d["position_name"],
                    "actual_points": d["actual_points"],
                    "projected_points": d["projected_points"],
                    "residual": d["residual"],
                    "minutes": d["actual_minutes"],
                }
                for d in top_negative
            ],
        }


differential_trainer = DifferentialTrainer()
