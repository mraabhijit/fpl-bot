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
