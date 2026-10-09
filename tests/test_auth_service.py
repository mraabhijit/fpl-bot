import pytest
from pathlib import Path
from fpl_bot.services.fpl_auth import FPLAuthService


def test_auth_service_persistence(tmp_path: Path, monkeypatch):
    # Real tokens in a developer's .env must not leak into this test
    monkeypatch.setattr("fpl_bot.services.fpl_auth.settings.fpl_access_token", "")
    monkeypatch.setattr("fpl_bot.services.fpl_auth.settings.fpl_refresh_token", "")
    session_file = tmp_path / "session_test.json"
    service = FPLAuthService(session_path=session_file)

    assert service.is_authenticated() is False

    # Login with token
    service._save_session("dummy_access_token_123", "dummy_refresh_token_456")
    assert service.is_authenticated() is True
    assert service._access_token == "dummy_access_token_123"

    # Reload from session file
    service2 = FPLAuthService(session_path=session_file)
    assert service2.is_authenticated() is True
    assert service2._access_token == "dummy_access_token_123"

    # Check auth headers
    headers = service2.get_auth_headers()
    assert "X-API-Authorization" in headers
    assert headers["X-API-Authorization"] == "Bearer dummy_access_token_123"

    # Logout
    service2.logout()
    assert service2.is_authenticated() is False
    assert not session_file.exists()


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code, self._payload = status_code, payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _service_with_post(tmp_path, monkeypatch, response=None, exc=None):
    monkeypatch.setattr("fpl_bot.services.fpl_auth.settings.fpl_access_token", "")
    monkeypatch.setattr("fpl_bot.services.fpl_auth.settings.fpl_refresh_token", "")
    service = FPLAuthService(session_path=tmp_path / "s.json")
    service._refresh_token = "SECRET-REFRESH"

    def fake_post(self, *args, **kwargs):
        if exc:
            raise exc
        return response

    monkeypatch.setattr("httpx.Client.post", fake_post)
    return service


def test_refresh_failure_reports_oauth_error_without_leaking_token(tmp_path, monkeypatch):
    resp = _FakeResponse(400, {"error": "invalid_grant", "error_description": "refresh token expired"})
    service = _service_with_post(tmp_path, monkeypatch, resp)
    assert service.refresh() is False
    assert "HTTP 400" in service.last_refresh_error and "invalid_grant" in service.last_refresh_error
    assert "SECRET-REFRESH" not in service.last_refresh_error


def test_refresh_failure_reports_network_error(tmp_path, monkeypatch):
    service = _service_with_post(tmp_path, monkeypatch, exc=TimeoutError())
    assert service.refresh() is False
    assert "TimeoutError" in service.last_refresh_error


def test_refresh_success_saves_rotated_tokens(tmp_path, monkeypatch):
    resp = _FakeResponse(200, {"access_token": "new-access", "refresh_token": "new-refresh"})
    service = _service_with_post(tmp_path, monkeypatch, resp)
    assert service.refresh() is True
    assert service._access_token == "new-access" and service._refresh_token == "new-refresh"
    assert service.last_refresh_error is None


def test_refresh_without_token_says_so(tmp_path, monkeypatch):
    service = _service_with_post(tmp_path, monkeypatch, _FakeResponse(200, {}))
    service._refresh_token = None
    assert service.refresh() is False and "no refresh token" in service.last_refresh_error
