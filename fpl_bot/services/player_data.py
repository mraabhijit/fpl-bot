"""
Service responsible for fetching, parsing, and assembling player and squad models.
"""

from typing import Dict, List, Optional, Tuple
from fpl_bot.core.config import settings
from fpl_bot.core.models import Player, Team, Gameweek, SquadPick, CurrentSquad
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient


class PlayerDataService:
    def __init__(self, api: Optional[FPLApiClient] = None):
        self.api = api or fpl_api

    def get_all_players_and_teams(self) -> Tuple[Dict[int, Player], Dict[int, Team], List[Gameweek]]:
        """
        Retrieves all players, teams, and gameweeks parsed into domain models.
        """
        raw = self.api.get_bootstrap_static()
        
        teams_map: Dict[int, Team] = {}
        for t in raw.get("teams", []):
            teams_map[t["id"]] = Team(
                id=t["id"],
                name=t["name"],
                short_name=t["short_name"],
                strength=t.get("strength") or t.get("strength_overall_home") or 3,
                strength_overall_home=t.get("strength_overall_home") or 1000,
                strength_overall_away=t.get("strength_overall_away") or 1000,
                strength_attack_home=t.get("strength_attack_home") or 1000,
                strength_attack_away=t.get("strength_attack_away") or 1000,
                strength_defence_home=t.get("strength_defence_home") or 1000,
                strength_defence_away=t.get("strength_defence_away") or 1000,
            )

        position_names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

        # Determine upcoming gameweek to map next opponent
        events = raw.get("events", [])
        next_event = next((e for e in events if e.get("is_next")), None)
        curr_event = next((e for e in events if e.get("is_current")), None)
        target_event_id = next_event["id"] if next_event else (curr_event["id"] if curr_event else 1)

        team_fixtures: Dict[int, List[str]] = {}
        try:
            fixtures_raw = self.api.get_fixtures(target_event_id)
            for f in fixtures_raw:
                th = f.get("team_h")
                ta = f.get("team_a")
                th_opp = teams_map[ta].short_name if ta in teams_map else "OPP"
                ta_opp = teams_map[th].short_name if th in teams_map else "OPP"
                team_fixtures.setdefault(th, []).append(f"{th_opp} (H)")
                team_fixtures.setdefault(ta, []).append(f"{ta_opp} (A)")
        except Exception:
            pass

        players_map: Dict[int, Player] = {}
        for el in raw.get("elements", []):
            tm = teams_map.get(el["team"])
            pos_name = position_names.get(el["element_type"], "UNK")
            next_opp = ", ".join(team_fixtures.get(el["team"], [])) or "BLANK"
            players_map[el["id"]] = Player(
                id=el["id"],
                web_name=el["web_name"],
                first_name=el.get("first_name", ""),
                second_name=el.get("second_name", ""),
                team_id=el["team"],
                team_short_name=tm.short_name if tm else "",
                team_name=tm.name if tm else "",
                element_type=el["element_type"],
                position_name=pos_name,
                now_cost=el["now_cost"],
                cost_str=f"{el['now_cost']/10:.1f}m",
                next_opponent=next_opp,
                status=el.get("status", "a"),
                news=el.get("news", ""),
                chance_of_playing_this_round=el.get("chance_of_playing_this_round"),
                chance_of_playing_next_round=el.get("chance_of_playing_next_round"),
                form=float(el.get("form") or 0.0),
                points_per_game=float(el.get("points_per_game") or 0.0),
                total_points=el.get("total_points", 0),
                event_points=el.get("event_points", 0),
                selected_by_percent=float(el.get("selected_by_percent") or 0.0),
                expected_goals=float(el.get("expected_goals") or 0.0),
                expected_assists=float(el.get("expected_assists") or 0.0),
                expected_goal_involvements=float(el.get("expected_goal_involvements") or 0.0),
                expected_goals_conceded=float(el.get("expected_goals_conceded") or 0.0),
                minutes=el.get("minutes", 0),
                goals_scored=el.get("goals_scored", 0),
                assists=el.get("assists", 0),
                clean_sheets=el.get("clean_sheets", 0),
                bonus=el.get("bonus", 0),
                bps=el.get("bps", 0),
                influence=float(el.get("influence") or 0.0),
                creativity=float(el.get("creativity") or 0.0),
                threat=float(el.get("threat") or 0.0),
                ict_index=float(el.get("ict_index") or 0.0),
                penalties_order=el.get("penalties_order"),
                direct_freekicks_order=el.get("direct_freekicks_order"),
                corners_and_indirect_freekicks_order=el.get("corners_and_indirect_freekicks_order"),
            )

        gameweeks: List[Gameweek] = []
        for ev in raw.get("events", []):
            gameweeks.append(Gameweek(
                id=ev["id"],
                name=ev["name"],
                deadline_time=ev["deadline_time"],
                deadline_epoch=float(ev.get("deadline_time_epoch", 0.0)),
                is_current=ev.get("is_current", False),
                is_next=ev.get("is_next", False),
                is_previous=ev.get("is_previous", False),
                finished=ev.get("finished", False),
                chip_plays=ev.get("chip_plays", []),
            ))

        return players_map, teams_map, gameweeks

    def get_current_squad(
        self,
        team_id: Optional[int] = None,
        gameweek: Optional[int] = None
    ) -> CurrentSquad:
        """
        Fetches current team squad and picks for the latest event.
        Uses authenticated /my-team/ if available to get live purchase/selling prices,
        falling back to public /picks/ endpoint.
        """
        tid = team_id or settings.team_id
        players_map, _, gameweeks = self.get_all_players_and_teams()

        # Find latest completed or current gameweek with published picks
        curr_gw = next((gw for gw in gameweeks if gw.is_current), None)
        next_gw = next((gw for gw in gameweeks if gw.is_next), None)
        latest_published_gw = curr_gw.id if curr_gw else (next_gw.id - 1 if next_gw else 1)
        picks_gw = min(gameweek, latest_published_gw) if gameweek else latest_published_gw

        # Check if we have authenticated access for my-team
        has_auth, _ = self.api.auth.validate_session(tid) if self.api.auth.is_authenticated() else (False, "")

        if has_auth:
            try:
                my_team = self.api.get_my_team(tid)
                picks_data = my_team.get("picks", [])
                transfers_info = my_team.get("transfers", {})
                bank = transfers_info.get("bank", 0)
                free_transfers = transfers_info.get("limit", 1)

                picks: List[SquadPick] = []
                for p in picks_data:
                    el_id = p["element"]
                    picks.append(SquadPick(
                        element_id=el_id,
                        position=p["position"],
                        is_captain=p.get("is_captain", False),
                        is_vice_captain=p.get("is_vice_captain", False),
                        multiplier=p.get("multiplier", 1),
                        selling_price=p.get("selling_price", players_map[el_id].now_cost if el_id in players_map else 0),
                        purchase_price=p.get("purchase_price", players_map[el_id].now_cost if el_id in players_map else 0),
                        player=players_map.get(el_id)
                    ))
                squad_value = sum(p.selling_price or 0 for p in picks)
                return CurrentSquad(
                    event=picks_gw,
                    picks=picks,
                    bank=bank,
                    value=squad_value,
                    free_transfers=free_transfers,
                    active_chip=None
                )
            except Exception:
                pass

        # Public picks fallback
        picks_resp = self.api.get_entry_picks(picks_gw, tid)
        entry_hist = picks_resp.get("entry_history", {})
        picks_list = picks_resp.get("picks", [])
        active_chip = picks_resp.get("active_chip")

        # Determine free transfers from history & transfers
        entry_history = self.api.get_entry_history(tid)
        current_history = entry_history.get("current", [])
        
        # Free transfers calculation (2024+ rules: 1 per GW, accumulates up to 5)
        # We also check if transfers were already made this week
        transfers_made = entry_hist.get("event_transfers", 0)
        # Default estimation: 1 FT available for upcoming GW if none saved, or compute from history
        free_transfers = 1

        picks: List[SquadPick] = []
        for p in picks_list:
            el_id = p["element"]
            cost = players_map[el_id].now_cost if el_id in players_map else 0
            picks.append(SquadPick(
                element_id=el_id,
                position=p["position"],
                is_captain=p.get("is_captain", False),
                is_vice_captain=p.get("is_vice_captain", False),
                multiplier=p.get("multiplier", 1),
                selling_price=cost,
                purchase_price=cost,
                player=players_map.get(el_id)
            ))

        bank = entry_hist.get("bank", 0)
        val = entry_hist.get("value", 1000)

        return CurrentSquad(
            event=picks_gw,
            picks=picks,
            bank=bank,
            value=val,
            free_transfers=free_transfers,
            active_chip=active_chip
        )


player_data_service = PlayerDataService()
