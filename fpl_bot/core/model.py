"""
Hybrid points model: gradient boosting on point-in-time features, with the hand-built heuristic
expected-points estimate (``heuristic_xp``) supplied as a feature and kept as the baseline to beat.
Predictions are per fixture; ``gameweek_predictions`` sums them so double gameweeks are handled.
"""

from typing import Dict, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from fpl_bot.core.features import feature_columns


class PointsModel:
    def __init__(self, params: Optional[Dict] = None):
        self.params = params or dict(
            loss="squared_error", learning_rate=0.04, max_iter=350, max_depth=5,
            min_samples_leaf=60, l2_regularization=2.0, random_state=0,
        )
        self.columns: list[str] = []
        self.model: Optional[HistGradientBoostingRegressor] = None

    def fit(self, feats: pd.DataFrame) -> "PointsModel":
        """Fit on played rows of a ``build_features`` frame."""
        train = feats[feats["played"]]
        self.columns = feature_columns(train)
        self.model = HistGradientBoostingRegressor(**self.params)
        self.model.fit(train[self.columns], train["total_points"])
        return self

    def predict_fixtures(self, feats: pd.DataFrame) -> pd.Series:
        """Predicted points per fixture row, floored at 0 (a player cannot score below -3 on average)."""
        pred = self.model.predict(feats[self.columns])
        return pd.Series(np.maximum(pred, 0.0), index=feats.index, name="xp")

    def gameweek_predictions(self, feats: pd.DataFrame) -> pd.DataFrame:
        """Sums fixture predictions into one row per (name, season, round): ``xp``."""
        tmp = feats[["name", "season_idx", "round"]].copy()
        tmp["xp"] = self.predict_fixtures(feats)
        return tmp.groupby(["name", "season_idx", "round"], sort=False, as_index=False)["xp"].sum()


def prediction_metrics(actual: pd.Series, predicted: pd.Series) -> Dict[str, float]:
    err = predicted - actual
    return {
        "mae": float(err.abs().mean()),
        "rmse": float(np.sqrt((err ** 2).mean())),
        "spearman": float(pd.concat([actual, predicted], axis=1).corr(method="spearman").iloc[0, 1]),
    }
