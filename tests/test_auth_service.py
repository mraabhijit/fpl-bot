import pytest
from pathlib import Path
from fpl_bot.services.fpl_auth import FPLAuthService


def test_auth_service_persistence(tmp_path: Path):
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
