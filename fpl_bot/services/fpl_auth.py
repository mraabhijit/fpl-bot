"""
Dedicated authentication service isolated as required by Section 4 of FPL-Optimizer.md.
Never logs credentials or exposes tokens.
Handles token persistence, refresh, validation, and header injection.
"""

import json
import os
from pathlib import Path
from typing import Dict, Optional, Tuple
import httpx
from fpl_bot.core.config import settings


class FPLAuthService:
    def __init__(self, session_path: Optional[Path] = None):
        self.session_path = session_path or settings.session_file
        self.authority = settings.auth_issuer_url
        self.token_endpoint = f"{self.authority}/token"
        self.client_id = settings.auth_client_id
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._load_session()

    def _load_session(self):
        """Loads securely persisted session tokens if present."""
        if self.session_path.exists():
            try:
                with open(self.session_path, "r") as f:
                    data = json.load(f)
                    self._access_token = data.get("access_token")
                    self._refresh_token = data.get("refresh_token")
            except Exception:
                self._access_token = None
                self._refresh_token = None
        elif settings.fpl_access_token:
            self._access_token = settings.fpl_access_token
            self._refresh_token = settings.fpl_refresh_token

    def _save_session(self, access_token: str, refresh_token: Optional[str] = None):
        """Saves session with restrictive file permissions."""
        self._access_token = access_token
        if refresh_token:
            self._refresh_token = refresh_token

        data = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
        }
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.session_path, "w") as f:
            json.dump(data, f)
        try:
            os.chmod(self.session_path, 0o600)
        except OSError:
            pass

    def login_with_token(self, access_token: str, refresh_token: Optional[str] = None) -> bool:
        """Sets and validates an existing access token / cookie from official browser session."""
        self._save_session(access_token, refresh_token)
        is_valid, _ = self.validate_session()
        return is_valid

    def refresh(self) -> bool:
        """Refreshes access token using OAuth refresh_token grant if available."""
        if not self._refresh_token:
            return False

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(
                    self.token_endpoint,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._refresh_token,
                        "client_id": self.client_id,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                if res.status_code == 200:
                    data = res.json()
                    new_token = data.get("access_token")
                    new_refresh = data.get("refresh_token", self._refresh_token)
                    if new_token:
                        self._save_session(new_token, new_refresh)
                        return True
        except Exception:
            pass
        return False

    def validate_session(self, team_id: Optional[int] = None) -> Tuple[bool, str]:
        """
        Validates whether current authenticated session is active and has private access.
        Uses /api/my-team/{team_id}/ to verify write authorization.
        """
        if not self._access_token:
            return False, "No active access token found"

        tid = team_id or settings.team_id
        url = f"{settings.fpl_base_url}/my-team/{tid}/"
        headers = self.get_auth_headers()

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.get(url, headers=headers)
                if res.status_code == 200:
                    return True, "Session valid and authorized"
                elif res.status_code in (401, 403):
                    # Try refreshing once
                    if self._refresh_token and self.refresh():
                        res2 = client.get(url, headers=self.get_auth_headers())
                        if res2.status_code == 200:
                            return True, "Session refreshed and authorized"
                    return False, f"Session expired or unauthorized (status {res.status_code})"
                else:
                    return False, f"Unexpected response validating session (status {res.status_code})"
        except Exception as e:
            return False, f"Network error during session validation: {str(e)}"

    def logout(self):
        """Clears local persisted session."""
        self._access_token = None
        self._refresh_token = None
        if self.session_path.exists():
            try:
                self.session_path.unlink()
            except OSError:
                pass

    def get_auth_headers(self) -> Dict[str, str]:
        """
        Returns headers for official API requests matching browser behavior.
        Token is never logged or exposed.
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Referer": "https://fantasy.premierleague.com/",
            "Origin": "https://fantasy.premierleague.com",
            "Accept": "application/json",
        }
        if self._access_token:
            # Matches FPL SPA client behavior: X-API-Authorization: Bearer <token>
            headers["X-API-Authorization"] = f"Bearer {self._access_token}"
        return headers

    def is_authenticated(self) -> bool:
        """Fast check if token is present in memory."""
        return bool(self._access_token)


auth_service = FPLAuthService()
