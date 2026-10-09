"""
Per-gameweek view of the manager's actual team for the dashboard: the lineup that played (or is saved for an
upcoming gameweek), real points so far and the model's stored prediction for each player.

Selectable gameweeks run from the first gameweek the bot made a recommendation for up to the gameweek after the
latest finished one, because nothing further ahead has a prediction.
"""

import time
from typing import Any, Dict, List, Optional, Tuple

from fpl_bot.core.config import settings
from fpl_bot.core.database import db
from fpl_bot.core.models import Player
from fpl_bot.services.fpl_api import fpl_api, FPLApiClient
from fpl_bot.services.player_data import player_data_service, PlayerDataService

TRIPLE_CAPTAIN = "3xc"
BENCH_BOOST = "bboost"


def gameweek_status(event: Dict[str, Any], now: Optional[float] = None) -> str:
    """finished (FPL has closed it), live (deadline passed, results still coming) or upcoming."""
    if event.get("finished"):
        return "finished"
    now = time.time() if now is None else now
    return "live" if now >= float(event.get("deadline_time_epoch") or 0) else "upcoming"


def selectable_gameweeks(first_prediction_gw: Optional[int], latest_finished: int, last_gw: int) -> List[int]:
    """First prediction .. the gameweek after the latest finished one (further ones have no prediction)."""
    last = min(last_gw, latest_finished + 1)
    first = min(first_prediction_gw or last, last)
    return list(range(first, last + 1))


def default_gameweek(statuses: Dict[int, str]) -> int:
    """The gameweek in progress if there is one, else the newest selectable (the upcoming one)."""
    live = [g for g, s in statuses.items() if s == "live"]
    return max(live) if live else max(statuses)


def apply_automatic_subs(xi: List[int], bench: List[int], subs: List[Dict[str, Any]]) -> Tuple[List[int], List[int], Dict[int, str]]:
    """Moves auto-subbed players between the XI and the bench; returns the new lists and a label per moved player."""
    xi, bench, labels = list(xi), list(bench), {}
    for s in subs:
        out_id, in_id = s["element_out"], s["element_in"]
        if out_id in xi and in_id in bench:
            xi[xi.index(out_id)] = in_id
            bench[bench.index(in_id)] = out_id
            labels[in_id], labels[out_id] = "Subbed on", "Subbed off"
    return xi, bench, labels


def fixture_labels(fixtures: List[Dict[str, Any]], teams_short: Dict[int, str]) -> Dict[int, Dict[str, Any]]:
    """Per team: opponent text such as 'LEE (H)' (joined for double gameweeks) and whether its matches are done."""
    out: Dict[int, Dict[str, Any]] = {}
    for f in fixtures:
        done = bool(f.get("finished") or f.get("finished_provisional"))
        started = bool(f.get("started") or done)
        for team, opp, side in ((f["team_h"], f["team_a"], "H"), (f["team_a"], f["team_h"], "A")):
            e = out.setdefault(team, {"opp": [], "done": [], "started": []})
            e["opp"].append(f"{teams_short.get(opp, '?')} ({side})")
            e["done"].append(done)
            e["started"].append(started)
    labels = {}
    for team, e in out.items():
        state = "done" if all(e["done"]) else ("live" if any(e["started"]) else "pending")
        labels[team] = {"opponent": ", ".join(e["opp"]), "state": state}
    return labels


class GameweekViewService:
    def __init__(self, api: Optional[FPLApiClient] = None, player_data: Optional[PlayerDataService] = None):
        self.api = api or fpl_api
        self.player_data = player_data or player_data_service

    # ---- index -------------------------------------------------------------------------------
    def index(self) -> Dict[str, Any]:
        events = {e["id"]: e for e in self.api.get_bootstrap_static()["events"]}
        latest_finished = max((g for g, e in events.items() if e["finished"]), default=0)
        gws = selectable_gameweeks(db.get_first_recommendation_gameweek(), latest_finished, max(events))
        statuses = {g: gameweek_status(events[g]) for g in gws}
        stored = set(db.get_recommendation_gameweeks())
        return {
            "default": default_gameweek(statuses),
            "gameweeks": [
                {"id": g, "status": statuses[g], "name": events[g]["name"],
                 "has_prediction": g in stored or bool(db.get_projection_snapshots(g))}
                for g in gws
            ],
        }

    # ---- one gameweek ---------------------------------------------------------------------------
    def _live_points(self, gw: int, finished: bool) -> Dict[int, int]:
        from fpl_bot.services.forecast_service import forecast_service
        live = forecast_service.live_payload(gw, finished)
        return {el["id"]: el.get("stats", {}).get("total_points", 0) for el in live.get("elements", [])}

    def _predictions(self, gw: int, status: str, players: Dict[int, Player]) -> Dict[int, float]:
        stored = db.get_projection_snapshots(gw)
        if stored:
            return {pid: float(row["base_xp"]) for pid, row in stored.items()}
        if status != "upcoming":
            return {}  # past or live gameweeks must not be re-predicted with hindsight
        from fpl_bot.agents.availability_agent import availability_agent
        from fpl_bot.agents.fixture_agent import fixture_agent
        from fpl_bot.agents.projection_agent import projection_agent
        _, teams, _ = self.player_data.get_all_players_and_teams()
        projections = projection_agent.generate_all_projections(
            list(players.values()), gw,
            fixture_agent.analyze_all_teams(list(teams.values()), gw),
            availability_agent.evaluate_squad_availability(list(players.values())),
        )
        return {pid: p.expected_fpl_points for pid, p in projections.items()}

    def view(self, gw: int) -> Dict[str, Any]:
        events = {e["id"]: e for e in self.api.get_bootstrap_static()["events"]}
        event = events[gw]
        status = gameweek_status(event)
        players, teams, _ = self.player_data.get_all_players_and_teams()
        teams_short = {t.id: t.short_name for t in teams.values()}
        fx = fixture_labels(self.api.get_fixtures(gw), teams_short)

        chip, subs, source = None, [], "picks"
        if status == "upcoming":
            squad = self.player_data.get_current_squad()
            picks = [{"element": p.element_id, "position": p.position, "is_captain": p.is_captain,
                      "is_vice_captain": p.is_vice_captain, "multiplier": 2 if p.is_captain else 1}
                     for p in squad.picks]
            points, source = {}, squad.source
        else:
            resp = self.api.get_entry_picks(gw, settings.team_id)
            picks, chip, subs = resp.get("picks", []), resp.get("active_chip"), resp.get("automatic_subs", [])
            points = self._live_points(gw, status == "finished")

        picks = sorted(picks, key=lambda p: p["position"])
        by_id = {p["element"]: p for p in picks}
        xi_ids = [p["element"] for p in picks if p["position"] <= 11]
        bench_ids = [p["element"] for p in picks if p["position"] > 11]
        xi_ids, bench_ids, sub_labels = apply_automatic_subs(xi_ids, bench_ids, subs)
        preds = self._predictions(gw, status, players)
        bench_slots = ["GK Sub", "Sub 1", "Sub 2", "Sub 3"]

        def card(pid: int, bench_idx: Optional[int] = None) -> Dict[str, Any]:
            p, pick = players[pid], by_id.get(pid, {})
            mult = pick.get("multiplier", 1) if bench_idx is None or chip == BENCH_BOOST else 1
            mult = mult if pick.get("is_captain") else 1
            label = fx.get(p.team_id, {"opponent": "BLANK", "state": "none"})
            base = points.get(pid, 0)
            xp = preds.get(pid)
            return {
                "id": pid, "web_name": p.web_name, "first_name": p.first_name, "second_name": p.second_name,
                "team_short_name": p.team_short_name, "team_name": p.team_name,
                "position_name": p.position_name, "element_type": p.element_type,
                "now_cost": p.now_cost, "now_cost_str": f"£{p.now_cost / 10:.1f}m",
                "next_opponent": label["opponent"],
                "points_state": "upcoming" if status == "upcoming" else label["state"],
                "has_prediction": xp is not None,
                "expected_points": round(xp, 1) if xp is not None else None,
                "predicted_points": round(xp * max(mult, 1), 1) if xp is not None else None,
                "actual_points": base * max(mult, 1), "base_actual_points": base,
                "is_captain": bool(pick.get("is_captain")), "is_vice_captain": bool(pick.get("is_vice_captain")),
                "sub_slot_label": sub_labels.get(pid) or (bench_slots[bench_idx] if bench_idx is not None else None),
            }

        xi = [card(i) for i in xi_ids]
        bench = [card(i, k) for k, i in enumerate(bench_ids)]
        counts = [sum(1 for p in xi if p["element_type"] == t) for t in (2, 3, 4)]
        return {
            "gameweek": gw, "status": status, "name": event["name"], "source": source,
            "has_prediction": bool(preds),
            "team": {
                "gameweek": gw, "formation": "-".join(map(str, counts)), "status": status,
                "is_bench_boost": chip == BENCH_BOOST, "active_chip": chip,
                "total_xp": 0.0, "xi_xp": 0.0, "bench_xp": 0.0,
                "actual_total_pts": sum(p["actual_points"] for p in xi),
                "starting_xi": xi, "bench": bench,
            },
        }


gameweek_view_service = GameweekViewService()
