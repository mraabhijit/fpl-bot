"""
FPL API client providing defensive, version-tolerant, and cached access to FPL endpoints.
Enforces caching to prevent rate limiting (Section 3).
"""

import time
from typing import Any, Dict, List, Optional
import httpx
from fpl_bot.core.config import settings
from fpl_bot.services.fpl_auth import auth_service, FPLAuthService


class FPLApiClient:
    def __init__(self, auth: Optional[FPLAuthService] = None):
        self.auth = auth or auth_service
        self.base_url = settings.fpl_base_url
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 300  # 5 minutes default TTL

    def _get(self, endpoint: str, auth_required: bool = False, use_cache: bool = True) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        now = time.time()

        if use_cache and not auth_required and endpoint in self._cache:
            ts, cached_data = self._cache[endpoint]
            if now - ts < self._cache_ttl:
                return cached_data

        headers = self.auth.get_auth_headers() if auth_required else {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json"
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    data = res.json()
                    if use_cache and not auth_required:
                        self._cache[endpoint] = (now, data)
                    return data
                elif res.status_code == 403 and auth_required:
                    raise PermissionError("FPL API returned 403 Forbidden: authentication required or expired.")
                elif res.status_code == 404:
                    raise FileNotFoundError(f"FPL API resource not found at {url}")
                else:
                    raise RuntimeError(f"FPL API request failed: {url} returned HTTP {res.status_code}")
        except httpx.RequestError as e:
            raise ConnectionError(f"Network error contacting FPL API at {url}: {str(e)}")

    def get_bootstrap_static(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetches bootstrap-static containing elements, teams, events, game settings."""
        if force_refresh and "bootstrap-static/" in self._cache:
            del self._cache["bootstrap-static/"]
        return self._get("bootstrap-static/")

    def get_entry(self, team_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetches manager details and mini-leagues for a team."""
        tid = team_id or settings.team_id
        return self._get(f"entry/{tid}/")

    def get_entry_history(self, team_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetches past seasons, current gameweeks history, and chips played."""
        tid = team_id or settings.team_id
        return self._get(f"entry/{tid}/history/")

    def get_entry_transfers(self, team_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetches all transfers made by the team this season."""
        tid = team_id or settings.team_id
        return self._get(f"entry/{tid}/transfers/")

    def get_entry_picks(self, gameweek: int, team_id: Optional[int] = None) -> Dict[str, Any]:
        """Fetches squad picks, captain, vice-captain, and chip for a specific gameweek."""
        tid = team_id or settings.team_id
        return self._get(f"entry/{tid}/event/{gameweek}/picks/")

    def get_my_team(self, team_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Fetches live private team state including current selling and purchase prices.
        Requires authenticated session.
        """
        tid = team_id or settings.team_id
        return self._get(f"my-team/{tid}/", auth_required=True, use_cache=False)

    def get_fixtures(self, gameweek: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetches fixtures for the season or a specific gameweek."""
        if gameweek:
            return self._get(f"fixtures/?event={gameweek}")
        return self._get("fixtures/")

    def get_element_summary(self, player_id: int) -> Dict[str, Any]:
        """Fetches historical match-by-match data and upcoming fixtures for a player."""
        return self._get(f"element-summary/{player_id}/")

    def get_event_live(self, gameweek: int) -> Dict[str, Any]:
        """Fetches live gameweek performance and underlying stats."""
        return self._get(f"event/{gameweek}/live/", use_cache=False)

    def get_classic_league_standings(self, league_id: int) -> Dict[str, Any]:
        """Fetches standings for a classic mini-league."""
        return self._get(f"leagues-classic/{league_id}/standings/")


fpl_api = FPLApiClient()
