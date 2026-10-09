"""
Forecast service: trains the points model on past seasons plus the current season so far, and
predicts every player's expected points for an upcoming gameweek (sum over that gameweek's fixtures).
"""

import json
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from fpl_bot.core.config import settings
from fpl_bot.core.features import build_features
from fpl_bot.core.model import PointsModel
from fpl_bot.data.history import CACHE_DIR, load_current_season, load_past_seasons, season_index
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class ForecastService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self._cache: Dict[Tuple[int, int], Dict[int, float]] = {}
        self._past: Optional[pd.DataFrame] = None

    def _past_frame(self) -> pd.DataFrame:
        if self._past is None:
            self._past = load_past_seasons()
        return self._past

    def _live(self, gw: int, finished: bool) -> Dict[str, Any]:
        """Finished gameweeks never change, so their live payload is cached on disk."""
        path = CACHE_DIR / f"live_{season_index(settings.season)}_{gw}.json"
        if finished and path.exists():
            return json.loads(path.read_text())
        data = self.api.get_event_live(gw)
        if finished:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data))
        return data

    def live_payload(self, gw: int, finished: bool) -> Dict[str, Any]:
        """event/{gw}/live, cached on disk once the gameweek is finished."""
        return self._live(gw, finished)

    def current_frame(self, bootstrap: Dict[str, Any], fixtures: list) -> pd.DataFrame:
        events = {e["id"]: e for e in bootstrap["events"]}
        live = {}
        for gw, ev in events.items():
            if ev.get("finished") or ev.get("is_current"):
                live[gw] = self._live(gw, bool(ev.get("finished")))
        return load_current_season(bootstrap, fixtures, live, settings.season)

    def feature_frame(self) -> pd.DataFrame:
        bootstrap = self.api.get_bootstrap_static()
        fixtures = self.api.get_fixtures()
        frame = pd.concat([self._past_frame(), self.current_frame(bootstrap, fixtures)], ignore_index=True)
        return build_features(frame)

    def predict_gameweek(self, gameweek: int) -> Dict[int, float]:
        """Expected points by FPL element id for ``gameweek`` (0 for players with no fixture)."""
        bootstrap = self.api.get_bootstrap_static()
        finished = sum(1 for e in bootstrap["events"] if e.get("finished"))
        key = (gameweek, finished)
        if key in self._cache:
            return self._cache[key]

        feats = self.feature_frame()
        season = season_index(settings.season)
        model = PointsModel().fit(feats)
        target = feats[(feats["season_idx"] == season) & (feats["round"] == gameweek) & (~feats["played"])]
        gw_pred = model.gameweek_predictions(target).set_index("name")["xp"]
        name_to_id = {f"{e['first_name']} {e['second_name']}": e["id"] for e in bootstrap["elements"]}
        out = {name_to_id[n]: float(v) for n, v in gw_pred.items() if n in name_to_id}
        self._cache[key] = out
        return out


forecast_service = ForecastService()
