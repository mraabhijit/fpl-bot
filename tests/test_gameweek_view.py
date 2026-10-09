import pytest

from fpl_bot.core.models import Player, Team
from fpl_bot.services import gameweek_view as gv
from fpl_bot.services.gameweek_view import (
    GameweekViewService, apply_automatic_subs, default_gameweek, fixture_labels, gameweek_status,
    selectable_gameweeks,
)


def test_status_from_event_flags_and_deadline():
    assert gameweek_status({"finished": True, "deadline_time_epoch": 0}) == "finished"
    assert gameweek_status({"finished": False, "deadline_time_epoch": 100}, now=200) == "live"
    assert gameweek_status({"finished": False, "deadline_time_epoch": 300}, now=200) == "upcoming"


def test_selectable_range_stops_one_after_latest_finished():
    assert selectable_gameweeks(5, 5, 38) == [5, 6]
    assert selectable_gameweeks(5, 38, 38) == list(range(5, 39))   # season over: no GW39
    assert selectable_gameweeks(None, 5, 38) == [6]                # no predictions yet: just the next one
    assert selectable_gameweeks(9, 5, 38) == [6]                   # never start after the newest selectable


def test_default_is_the_live_gameweek_else_the_newest():
    assert default_gameweek({5: "finished", 6: "live"}) == 6
    assert default_gameweek({5: "finished", 6: "upcoming"}) == 6
    assert default_gameweek({6: "finished", 7: "upcoming"}) == 7


def test_automatic_subs_swap_between_xi_and_bench():
    xi, bench, labels = apply_automatic_subs([1, 2, 3], [12, 13], [{"element_out": 2, "element_in": 13}])
    assert xi == [1, 13, 3] and bench == [12, 2]
    assert labels == {13: "Subbed on", 2: "Subbed off"}
    # a sub that does not match the lineup is ignored rather than corrupting it
    assert apply_automatic_subs([1], [12], [{"element_out": 9, "element_in": 12}])[:2] == ([1], [12])


def test_fixture_labels_cover_double_gameweeks_and_match_state():
    fixtures = [
        {"team_h": 1, "team_a": 2, "finished": True, "started": True},
        {"team_h": 3, "team_a": 1, "finished": False, "started": False},
        {"team_h": 4, "team_a": 5, "finished": False, "started": True},
    ]
    labels = fixture_labels(fixtures, {1: "ARS", 2: "AVL", 3: "BOU", 4: "BRE", 5: "BHA"})
    assert labels[1] == {"opponent": "AVL (H), BOU (A)", "state": "live"}   # one played, one to come
    assert labels[2]["state"] == "done" and labels[3]["state"] == "pending" and labels[4]["state"] == "live"
    assert 99 not in labels   # blank teams are absent so the caller shows BLANK


# ---- full view with fakes ------------------------------------------------------------------------------

def make_players():
    spec = [(1, 1, 1), (2, 2, 1), (3, 2, 1), (4, 2, 1), (5, 3, 2), (6, 3, 2), (7, 3, 2), (8, 3, 2),
            (9, 4, 3), (10, 4, 3), (11, 4, 3), (12, 1, 4), (13, 2, 4), (14, 3, 4), (15, 4, 4)]
    names = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}
    return {pid: Player(id=pid, web_name=f"P{pid}", first_name="F", second_name=str(pid), team_id=team,
                        team_short_name=f"T{team}", team_name=f"Team{team}", element_type=pos,
                        position_name=names[pos], now_cost=50) for pid, pos, team in spec}


class FakeApi:
    def __init__(self, events):
        self.events = events

    def get_bootstrap_static(self):
        return {"events": self.events}

    def get_fixtures(self, gw):
        return [{"team_h": 1, "team_a": 2, "finished": True, "started": True},
                {"team_h": 3, "team_a": 4, "finished": True, "started": True}]

    def get_entry_picks(self, gw, team_id=None):
        picks = [{"element": i, "position": i, "is_captain": i == 9, "is_vice_captain": i == 10,
                  "multiplier": 2 if i == 9 else (1 if i <= 11 else 0)} for i in range(1, 16)]
        # player 8 never played: bench player 14 (a midfielder) was automatically subbed on
        return {"picks": picks, "active_chip": None, "automatic_subs": [{"element_out": 8, "element_in": 14}]}


class FakePlayerData:
    def get_all_players_and_teams(self):
        teams = {t: Team(id=t, name=f"Team{t}", short_name=f"T{t}") for t in (1, 2, 3, 4)}
        return make_players(), teams, []


@pytest.fixture
def service(monkeypatch):
    events = [{"id": 5, "name": "Gameweek 5", "finished": True, "deadline_time_epoch": 0},
              {"id": 6, "name": "Gameweek 6", "finished": False, "deadline_time_epoch": 9e12}]
    svc = GameweekViewService(api=FakeApi(events), player_data=FakePlayerData())
    from fpl_bot.services.forecast_service import forecast_service
    points = {i: 2 for i in range(1, 16)}
    points.update({8: 0, 9: 10, 14: 6})
    monkeypatch.setattr(forecast_service, "live_payload",
                        lambda gw, finished: {"elements": [{"id": i, "stats": {"total_points": v}} for i, v in points.items()]})
    monkeypatch.setattr(gv.db, "get_projection_snapshots", lambda gw: {})
    monkeypatch.setattr(gv.db, "get_recommendation_gameweeks", lambda: [5])
    monkeypatch.setattr(gv.db, "get_first_recommendation_gameweek", lambda: 5)
    return svc


def test_finished_gameweek_counts_captain_double_and_autosub(service):
    team = service.view(5)["team"]
    pts = {p["id"]: p["actual_points"] for p in team["starting_xi"]}
    assert 14 in pts and 8 not in pts            # the bench midfielder came on for the absentee
    assert pts[9] == 20                           # captain's 10 points doubled
    # seven players on 2, sub on 6, captain 20, two forwards on 2
    assert team["actual_total_pts"] == 7 * 2 + 6 + 20 + 2 + 2 == 44
    assert [p["id"] for p in team["bench"]] == [12, 13, 8, 15]
    assert next(p for p in team["starting_xi"] if p["id"] == 14)["sub_slot_label"] == "Subbed on"
    assert next(p for p in team["bench"] if p["id"] == 8)["sub_slot_label"] == "Subbed off"
    assert team["formation"] == "3-4-3"


def test_finished_gameweek_without_snapshot_is_not_repredicted(service):
    view = service.view(5)
    assert view["has_prediction"] is False
    assert all(p["expected_points"] is None for p in view["team"]["starting_xi"])


def test_stored_snapshot_is_used_for_predictions(service, monkeypatch):
    monkeypatch.setattr(gv.db, "get_projection_snapshots", lambda gw: {i: {"base_xp": 3.0} for i in range(1, 16)})
    view = service.view(5)
    cap = next(p for p in view["team"]["starting_xi"] if p["is_captain"])
    assert view["has_prediction"] and cap["expected_points"] == 3.0 and cap["predicted_points"] == 6.0


def test_index_lists_range_and_flags_predictions(service, monkeypatch):
    monkeypatch.setattr(gv.db, "get_projection_snapshots", lambda gw: {1: {}} if gw == 5 else {})
    idx = service.index()
    assert [g["id"] for g in idx["gameweeks"]] == [5, 6] and idx["default"] == 6
    assert [g["has_prediction"] for g in idx["gameweeks"]] == [True, False]
