"""
CI check that the FPL tokens in repo secrets still work, without ever refreshing them.

Refreshing in CI could rotate the refresh token and invalidate the copy used by the deployment, so this
only sends the access token once and reports what happened. Nothing from the response is printed:
CI logs may be public.
"""

import sys

import httpx

from fpl_bot.core.config import settings
from fpl_bot.services.fpl_auth import FPLAuthService


def main() -> int:
    if not settings.fpl_access_token:
        print("FAIL: FPL_ACCESS_TOKEN secret is missing or empty")
        return 1
    if not settings.fpl_refresh_token:
        print("WARN: FPL_REFRESH_TOKEN secret is missing; the deployment cannot renew an expired access token")
    if not settings.fpl_access_token.isascii():
        print("FAIL: FPL_ACCESS_TOKEN contains non-ASCII characters (truncated copy from DevTools?)")
        return 1

    auth = FPLAuthService(session_path=settings.session_file.with_name("ci_session_unused.json"))
    url = f"{settings.fpl_base_url}/my-team/{settings.team_id}/"
    try:
        res = httpx.get(url, headers=auth.get_auth_headers(), timeout=20.0)
    except httpx.HTTPError as exc:
        print(f"FAIL: network error reaching FPL ({type(exc).__name__})")
        return 1

    if res.status_code == 200 and "transfers" in res.json():
        print("OK: access token is valid and my-team returned transfer data")
        return 0
    if res.status_code in (401, 403):
        print(f"FAIL: access token rejected (HTTP {res.status_code}); it has expired, re-copy it into the secret")
        return 1
    print(f"FAIL: unexpected response from my-team (HTTP {res.status_code})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
