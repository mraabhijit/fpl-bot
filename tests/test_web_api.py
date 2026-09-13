import pytest
from fastapi.testclient import TestClient
from fpl_bot.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Overspent FC" in response.text
    assert "6834344" in response.text


def test_api_diagnostic(client):
    response = client.get("/api/diagnostic")
    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == 6834344
    assert data["team_name"] == "Overspent FC"
    assert data["fpl_connection"] == "OK"


def test_api_recommendation(client):
    response = client.get("/api/recommendation")
    assert response.status_code == 200
    data = response.json()
    assert "gameweek" in data
    assert "starting_xi" in data
    assert "recommended_team" in data
    assert "current_team" in data

    rec_team = data["recommended_team"]
    curr_team = data["current_team"]
    assert len(rec_team["starting_xi"]) == 11
    assert len(rec_team["bench"]) == 4
    assert len(curr_team["starting_xi"]) == 11
    assert len(curr_team["bench"]) == 4

    # Validate next_opponent, expected_points, actual_points, and predicted_points
    for p in rec_team["starting_xi"]:
        assert "next_opponent" in p
        assert p["next_opponent"] != ""
        assert "expected_points" in p
        assert "simulated_points" in p
        assert isinstance(p["expected_points"], (int, float))

    for p in curr_team["starting_xi"]:
        assert "next_opponent" in p
        assert "actual_points" in p
        assert "predicted_points" in p
        assert isinstance(p["actual_points"], (int, float))

    for p in rec_team["bench"]:
        assert "next_opponent" in p
        assert "sub_slot_label" in p
        assert p["sub_slot_label"] is not None

    # Check primary toggle buttons, secondary toggle buttons, and CSS classes in dashboard HTML
    dash_resp = client.get("/")
    assert "btn-toggle-rec" in dash_resp.text
    assert "btn-toggle-curr" in dash_resp.text
    assert "actual-mode-toggle" in dash_resp.text
    assert "btn-actual-pts" in dash_resp.text
    assert "btn-actual-pred" in dash_resp.text
    assert "p-opp" in dash_resp.text
    assert "p-xp" in dash_resp.text
    assert "p-actual" in dash_resp.text
    assert "p-xp" in dash_resp.text



def test_api_audits(client):
    response = client.get("/api/audits")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_backtests(client):
    response = client.get("/api/backtests")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_api_approval_cycle(client):
    rec_resp = client.get("/api/recommendation")
    rec = rec_resp.json()
    rec_id = rec["id"]

    # Approve
    resp = client.post("/api/approval", json={"recommendation_id": rec_id, "decision": "APPROVE"})
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "APPROVED"

    # Reject
    resp2 = client.post("/api/approval", json={"recommendation_id": rec_id, "decision": "REJECT"})
    assert resp2.status_code == 200
    assert resp2.json()["approval_status"] == "REJECTED"
