"""
Elite crowd consensus and market momentum service.
Polls top overall FPL managers (League 314) to compute elite effective ownership,
captaincy concentration, and event-level transfer velocity signals.
"""

import time
from typing import Any, Dict, List, Optional
from fpl_bot.core.database import db
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class ConsensusService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api
        self._cached_consensus: Optional[Dict[str, Any]] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 1800.0  # 30 minutes in-memory cache

    def get_elite_consensus(
        self,
        top_n: int = 15,
        gameweek: Optional[int] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Polls the top overall managers in the world from classic league 314,
        extracts their squad picks and captain choices, and returns aggregated ownership rates.
        """
        now = time.time()
        if not force_refresh and self._cached_consensus and (now - self._cache_timestamp < self._cache_ttl):
            return self._cached_consensus

        # Default fallback structure
        result: Dict[str, Any] = {
            "gameweek": gameweek or 0,
            "sample_size": 0,
            "elite_ownership": {},     # player_id -> fraction (0.0 to 1.0)
            "elite_captains": {},      # player_id -> count
            "top_managers": [],        # list of top manager metadata
            "market_momentum": {},     # player_id -> {net_transfers, transfer_momentum}
        }

        try:
            # 1. Fetch Overall standings (League 314)
            standings_resp = self.api.get_classic_league_standings(314)
            standings = standings_resp.get("standings", {}).get("results", [])[:top_n]
            if not standings:
                return result

            # Determine target gameweek if not specified
            if not gameweek:
                bootstrap = self.api.get_bootstrap_static()
                events = bootstrap.get("events", [])
                curr_event = next((e for e in events if e.get("is_current")), None)
                prev_event = next((e for e in events if e.get("is_previous")), None)
                target_gw = curr_event["id"] if curr_event else (prev_event["id"] if prev_event else 1)
            else:
                target_gw = gameweek

            result["gameweek"] = target_gw
            result["sample_size"] = len(standings)

            # 2. Sample squad picks and captains for top managers
            ownership_counts: Dict[int, int] = {}
            captain_counts: Dict[int, int] = {}
            managers_meta: List[Dict[str, Any]] = []

            for mgr in standings:
                entry_id = mgr.get("entry")
                if not entry_id:
                    continue

                managers_meta.append({
                    "entry_id": entry_id,
                    "rank": mgr.get("rank"),
                    "manager_name": mgr.get("player_name", ""),
                    "team_name": mgr.get("entry_name", ""),
                    "total_points": mgr.get("total", 0),
                    "event_points": mgr.get("event_total", 0),
                })

                try:
                    picks_resp = self.api.get_entry_picks(gameweek=target_gw, team_id=entry_id)
                    for pick in picks_resp.get("picks", []):
                        pid = pick.get("element")
                        if not pid:
                            continue
                        ownership_counts[pid] = ownership_counts.get(pid, 0) + 1
                        if pick.get("is_captain"):
                            captain_counts[pid] = captain_counts.get(pid, 0) + 1
                except Exception:
                    # Defensive handling for isolated individual manager fetch errors
                    continue

            total_sampled = max(1, len(managers_meta))
            result["elite_ownership"] = {
                pid: round(count / total_sampled, 3)
                for pid, count in ownership_counts.items()
            }
            result["elite_captains"] = captain_counts
            result["top_managers"] = managers_meta

            # 3. Compute market-wide transfer momentum from bootstrap-static
            try:
                bootstrap = self.api.get_bootstrap_static()
                market_mom: Dict[int, Dict[str, Any]] = {}
                for el in bootstrap.get("elements", []):
                    pid = el["id"]
                    tin = el.get("transfers_in_event", 0)
                    tout = el.get("transfers_out_event", 0)
                    net = tin - tout
                    # Normalize transfer velocity: 50,000 net transfers is ~1.0 momentum unit
                    normalized_mom = max(-2.0, min(2.0, net / 50000.0))
                    market_mom[pid] = {
                        "net_transfers_event": net,
                        "transfer_momentum": round(normalized_mom, 3),
                        "selected_by_percent": float(el.get("selected_by_percent") or 0.0),
                    }
                result["market_momentum"] = market_mom
            except Exception:
                pass

            self._cached_consensus = result
            self._cache_timestamp = now
            return result

        except Exception as e:
            # Fall back to empty consensus on network errors without disrupting optimization
            return result

    def get_player_consensus_signal(self, player_id: int) -> Dict[str, float]:
        """
        Retrieves normalized consensus and momentum signals for an individual player.
        """
        consensus = self.get_elite_consensus()
        elite_own = consensus.get("elite_ownership", {}).get(player_id, 0.0)
        cap_count = consensus.get("elite_captains", {}).get(player_id, 0)
        sample_size = max(1, consensus.get("sample_size", 1))
        captaincy_rate = cap_count / sample_size

        mom_data = consensus.get("market_momentum", {}).get(player_id, {})
        transfer_mom = float(mom_data.get("transfer_momentum", 0.0))

        return {
            "elite_ownership": float(elite_own),
            "elite_captaincy": round(captaincy_rate, 3),
            "transfer_momentum": transfer_mom,
        }


consensus_service = ConsensusService()
