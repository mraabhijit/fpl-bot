"""
Adaptive Differential Learning Trainer.
Trains online regularized error-correction models using weekly gameweek differentials.
Applies Empirical Bayes shrinkage and Multi-Factor Ridge Regression incorporating:
1. Shrunken historical residuals
2. Player form trajectory and xGI efficiency delta
3. Team attacking potency and defensive fragility dynamics
4. Elite crowd consensus ownership from top overall FPL managers
5. Market transfer velocity and momentum

Produces calibrated, bounded player projection adjustments clamped in [-max_delta, +max_delta].
"""

import math
from typing import Any, Dict, List, Optional, Tuple
from fpl_bot.core.database import db
from fpl_bot.services.consensus_service import consensus_service
from fpl_bot.services.team_form_service import team_form_service


TEAM_SHORT_TO_ID = {
    "ARS": 1, "AVL": 2, "BOU": 3, "BRE": 4, "BHA": 5,
    "CHE": 6, "CRY": 7, "EVE": 8, "FUL": 9, "IPS": 10,
    "LEI": 11, "LIV": 12, "MCI": 13, "MUN": 14, "NEW": 15,
    "NFO": 16, "SOU": 17, "TOT": 18, "WHU": 19, "WOL": 20
}

FEATURE_NAMES = [
    "intercept",
    "prior_residual",
    "form_efficiency",
    "team_attack_momentum",
    "elite_consensus_ownership",
    "market_transfer_momentum",
]

FEATURE_LABELS = {
    "intercept": "Baseline Bias",
    "prior_residual": "Historical Residual Prior",
    "form_efficiency": "Form Acceleration (GI vs xGI)",
    "team_attack_momentum": "Team Attacking Momentum",
    "elite_consensus_ownership": "Elite Manager Consensus",
    "market_transfer_momentum": "Market Transfer Momentum",
}


class DifferentialTrainer:
    def __init__(
        self,
        shrinkage_lambda: float = 3.0,
        max_delta: float = 2.0,
        ridge_alpha: float = 15.0
    ):
        self.shrinkage_lambda = shrinkage_lambda  # Shrinkage toward group mean for small samples
        self.max_delta = max_delta                # Maximum adjustment ceiling [-max_delta, +max_delta]
        self.ridge_alpha = ridge_alpha            # L2 Ridge regularization parameter
        self._cached_weights: Optional[Dict[str, Any]] = None

    def _solve_linear_system(self, A: List[List[float]], b: List[float]) -> List[float]:
        """
        Solves the linear system A * x = b via Gaussian elimination with partial pivoting.
        Standard library only, zero external dependencies.
        """
        n = len(b)
        M = [A[i][:] + [b[i]] for i in range(n)]

        for i in range(n):
            # Find maximum pivot in column i
            max_row = max(range(i, n), key=lambda r: abs(M[r][i]))
            M[i], M[max_row] = M[max_row], M[i]

            pivot = M[i][i]
            if abs(pivot) < 1e-12:
                continue

            for j in range(i, n + 1):
                M[i][j] /= pivot

            for r in range(n):
                if r != i:
                    factor = M[r][i]
                    for j in range(i, n + 1):
                        M[r][j] -= factor * M[i][j]

        return [M[i][n] for i in range(n)]

    def train(self, up_to_gw: Optional[int] = None) -> Dict[str, Any]:
        """
        Trains an adaptive multi-factor error-correction model on all differentials
        up to the specified gameweek.
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

            if p_pos in pos_stats:
                pos_stats[p_pos].append(res)

            if team:
                if team not in team_stats:
                    team_stats[team] = []
                team_stats[team].append(res)

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
        for pid, pdata in player_stats.items():
            res_list = pdata["residuals"]
            n = len(res_list)
            player_avg_res = sum(res_list) / n

            w_player = n / (n + self.shrinkage_lambda)

            pos = pdata["element_type"]
            team = pdata["team"]
            pos_prior = pos_means.get(pos, 0.0)
            team_prior = team_means.get(team, 0.0)
            blended_prior = 0.6 * pos_prior + 0.4 * team_prior

            raw_delta = (w_player * player_avg_res) + ((1.0 - w_player) * blended_prior)
            avg_xgi_delta = sum(pdata["xgi_deltas"]) / n
            efficiency_nudge = max(-0.5, min(0.5, avg_xgi_delta * 0.2))

            combined_delta = raw_delta + efficiency_nudge
            bounded_delta = max(-self.max_delta, min(self.max_delta, combined_delta))
            player_adjustments[str(pid)] = round(bounded_delta, 2)

        # 4. Extract Multi-Factor Features (Team Form & Elite Consensus)
        team_forms = team_form_service.get_all_team_form_metrics()
        consensus_data = consensus_service.get_elite_consensus(top_n=10)
        elite_own = consensus_data.get("elite_ownership", {})
        market_mom = consensus_data.get("market_momentum", {})

        # Construct Design Matrix X and Target y
        X: List[List[float]] = []
        y: List[float] = []

        for r in rows:
            pid = r["player_id"]
            tm_short = r.get("team_short_name", "")
            tid = TEAM_SHORT_TO_ID.get(tm_short, 0)
            tf = team_forms.get(tid, {})

            # Features:
            # 0: Intercept
            x0 = 1.0

            # 1: Prior shrunken residual
            x1 = player_adjustments.get(str(pid), 0.0)

            # 2: Form efficiency (actual GI - expected GI)
            act_gi = float(r.get("actual_goals", 0)) + float(r.get("actual_assists", 0))
            exp_gi = float(r.get("xg", 0.0) or 0.0) + float(r.get("xa", 0.0) or 0.0)
            x2 = act_gi - exp_gi

            # 3: Team attack momentum index
            x3 = float(tf.get("attack_momentum_index", 0.0))

            # 4: Elite consensus ownership
            x4 = float(elite_own.get(pid, 0.0))

            # 5: Market transfer momentum
            x5 = float(market_mom.get(pid, {}).get("transfer_momentum", 0.0))

            X.append([x0, x1, x2, x3, x4, x5])
            y.append(float(r["residual"]))

        # 5. Fit Multi-Factor Regularized Ridge Regression
        K = len(FEATURE_NAMES)
        XtX = [[0.0] * K for _ in range(K)]
        Xty = [0.0] * K

        for row_x, target_y in zip(X, y):
            for i in range(K):
                Xty[i] += row_x[i] * target_y
                for j in range(K):
                    XtX[i][j] += row_x[i] * row_x[j]

        # Apply L2 Ridge penalty to non-intercept features
        for i in range(1, K):
            XtX[i][i] += self.ridge_alpha

        learned_w = self._solve_linear_system(XtX, Xty)
        feature_weights = {
            FEATURE_NAMES[i]: round(learned_w[i], 4)
            for i in range(K)
        }

        # 6. Evaluate Model Performance
        total_sq_error = 0.0
        total_abs_error = 0.0
        n_samples = len(rows)

        for row_x, target_y in zip(X, y):
            raw_pred = sum(learned_w[j] * row_x[j] for j in range(K))
            bounded_pred = max(-self.max_delta, min(self.max_delta, raw_pred))
            err = target_y - bounded_pred
            total_abs_error += abs(err)
            total_sq_error += err ** 2

        mae = round(total_abs_error / n_samples, 3)
        rmse = round(math.sqrt(total_sq_error / n_samples), 3)
        baseline_sq_error = sum((target_y - global_mean) ** 2 for target_y in y)
        r2 = round(1.0 - (total_sq_error / max(1e-6, baseline_sq_error)), 3)

        checkpoint_payload = {
            "trained_after_gw": target_gw,
            "algorithm": "multi_factor_ridge_regression",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "sample_count": n_samples,
            "weights_json": {
                "feature_weights": feature_weights,
                "player_adjustments": player_adjustments,
                "position_means": {str(k): round(v, 3) for k, v in pos_means.items()},
                "team_means": {str(k): round(v, 3) for k, v in team_means.items()},
                "global_mean": round(global_mean, 3),
                "shrinkage_lambda": self.shrinkage_lambda,
                "max_delta": self.max_delta,
                "ridge_alpha": self.ridge_alpha,
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
                "algorithm": "multi_factor_ridge_regression",
                "mae": mae,
                "rmse": rmse,
                "r2": r2,
                "feature_weights": feature_weights,
                "players_count": len(player_adjustments),
            },
            result="SUCCESS"
        )

        return {
            "checkpoint_id": chk_id,
            "trained_after_gw": target_gw,
            "algorithm": "multi_factor_ridge_regression",
            "mae": mae,
            "rmse": rmse,
            "r2": r2,
            "sample_count": n_samples,
            "players_modeled": len(player_adjustments),
            "feature_weights": feature_weights,
        }

    def predict_adjustment(
        self,
        player_id: int,
        element_type: int = 3,
        team_short_name: Optional[str] = None,
        player: Optional[Any] = None,
        fixture_score: Optional[Any] = None
    ) -> float:
        """
        Infers the calibrated additive adjustment hat_delta for a player's baseline projection
        using the learned multi-factor regression model.
        Guaranteed to be clamped in [-max_delta, +max_delta].
        """
        if self._cached_weights is None:
            latest = db.get_latest_model_checkpoint()
            if latest and isinstance(latest.get("weights_json"), dict):
                self._cached_weights = latest["weights_json"]
            else:
                return 0.0

        feature_weights = self._cached_weights.get("feature_weights")
        player_adjustments = self._cached_weights.get("player_adjustments", {})

        # Baseline player prior residual
        pid_str = str(player_id)
        if pid_str in player_adjustments:
            x1 = float(player_adjustments[pid_str])
        else:
            pos_means = self._cached_weights.get("position_means", {})
            team_means = self._cached_weights.get("team_means", {})
            pos_prior = float(pos_means.get(str(element_type), 0.0))
            team_prior = float(team_means.get(str(team_short_name), 0.0)) if team_short_name else 0.0
            x1 = round((0.6 * pos_prior + 0.4 * team_prior) * 0.5, 2)

        # If multi-factor weights are trained and player domain object is available:
        if feature_weights and player:
            x0 = 1.0
            # Form acceleration: form (recent 30 days) minus season PPG
            p_form = getattr(player, "form", 0.0) or 0.0
            p_ppg = getattr(player, "points_per_game", 0.0) or 0.0
            x2 = float(p_form - p_ppg)

            # Team attacking momentum
            tm_id = getattr(player, "team_id", 0) or TEAM_SHORT_TO_ID.get(team_short_name or "", 0)
            team_form_data = team_form_service.get_all_team_form_metrics()
            x3 = float(team_form_data.get(tm_id, {}).get("attack_momentum_index", 0.0))

            # Elite consensus signals
            consensus_signals = consensus_service.get_player_consensus_signal(player_id)
            x4 = float(consensus_signals.get("elite_ownership", 0.0))
            x5 = float(consensus_signals.get("transfer_momentum", 0.0))

            feature_vec = [x0, x1, x2, x3, x4, x5]
            raw_delta = sum(
                feature_weights.get(FEATURE_NAMES[j], 0.0) * feature_vec[j]
                for j in range(len(FEATURE_NAMES))
            )
            return round(max(-self.max_delta, min(self.max_delta, raw_delta)), 2)

        # Fallback to single-factor shrunken delta
        return round(max(-self.max_delta, min(self.max_delta, x1)), 2)

    def get_differentials_summary(self, gameweek: Optional[int] = None) -> Dict[str, Any]:
        """
        Produces a rich structured summary of differentials, multi-factor weights,
        elite crowd consensus, and team form dynamics for UI and CLI display.
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

        # Elite consensus summary
        consensus_data = consensus_service.get_elite_consensus(top_n=15)
        elite_own = consensus_data.get("elite_ownership", {})
        elite_captains = consensus_data.get("elite_captains", {})

        # Enrich elite owned players with names
        player_names_map = {d["player_id"]: d["player_name"] for d in differentials}
        top_elite_players = []
        for pid, rate in sorted(elite_own.items(), key=lambda x: x[1], reverse=True)[:6]:
            top_elite_players.append({
                "player_id": pid,
                "player_name": player_names_map.get(pid, f"Player #{pid}"),
                "ownership_rate": round(rate * 100.0, 1),
                "captain_picks": elite_captains.get(pid, 0),
            })

        # Team form summary
        team_forms = team_form_service.get_all_team_form_metrics()
        top_attacking_teams = sorted(
            team_forms.values(),
            key=lambda x: x["goals_scored_per_match"],
            reverse=True
        )[:4]
        top_defending_teams = sorted(
            team_forms.values(),
            key=lambda x: x["goals_conceded_per_match"]
        )[:4]

        # Feature weights with descriptions
        weights_dict = {}
        if latest_chk and isinstance(latest_chk.get("weights_json"), dict):
            fw = latest_chk["weights_json"].get("feature_weights", {})
            for k, val in fw.items():
                weights_dict[k] = {
                    "label": FEATURE_LABELS.get(k, k),
                    "weight": val,
                    "interpretation": (
                        "Increases baseline expected points" if val > 0 else "Dampens baseline expected points"
                    ),
                }

        return {
            "gameweek": gameweek or (differentials[0]["gameweek"] if differentials else 0),
            "sample_count": len(differentials),
            "latest_checkpoint": latest_chk,
            "feature_weights": weights_dict,
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
            "elite_consensus": {
                "sample_size": consensus_data.get("sample_size", 0),
                "top_players": top_elite_players,
            },
            "team_form_leaders": {
                "top_attack": [
                    {
                        "team_id": t["team_id"],
                        "goals_scored_per_match": t["goals_scored_per_match"],
                        "momentum_index": t["attack_momentum_index"],
                    }
                    for t in top_attacking_teams
                ],
                "top_defense": [
                    {
                        "team_id": t["team_id"],
                        "goals_conceded_per_match": t["goals_conceded_per_match"],
                        "fragility_index": t["defense_fragility_index"],
                    }
                    for t in top_defending_teams
                ],
            }
        }


differential_trainer = DifferentialTrainer()
