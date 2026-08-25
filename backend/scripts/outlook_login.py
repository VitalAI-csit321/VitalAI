"""One-time interactive Outlook login for the inbound mail connector.

Run this by hand, once per mailbox, before enabling OUTLOOK_ENABLED:

    cd backend
    python scripts/outlook_login.py

It prints a URL and a code, waits for you to sign in with the mailbox the
clinic reads from, then writes the MSAL token cache to
settings.outlook_token_cache_path. From then on the app refreshes silently
via app.services.outlook_auth.get_access_token().

The device-code flow itself is Matthew's, from
Inbox_Handling/Outlook_Authentication.py; what is added here is persisting
the resulting cache so a server process never has to run this flow inline.

Re-run when the refresh token lapses (roughly 90 days of no use, or after the
account revokes consent). The symptom is OutlookAuthRequiredError in the
poller's logs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.services.outlook_auth import (  # noqa: E402
    SCOPES,
    build_app,
    load_cache,
    save_cache,
)


def main() -> int:
    if not settings.outlook_client_id:
        print("OUTLOOK_CLIENT_ID is not set. Add it to backend/.env first.")
        return 1

    cache = load_cache()
    app = build_app(cache)

    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            save_cache(cache)
            print(f"Already signed in as {accounts[0].get('username')}. Cache is valid.")
            return 0

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("Failed to create device authentication flow:")
        print(flow.get("error_description", flow))
        return 1

    # flow["message"] is the human-readable "go to <url> and enter <code>".
    print(flow["message"], flush=True)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print("Authentication failed:")
        print(result.get("error_description", result))
        return 1

    save_cache(cache)
    signed_in = app.get_accounts()
    username = signed_in[0].get("username") if signed_in else "unknown account"
    print(f"Signed in as {username}.")
    print(f"Token cache written to {settings.outlook_token_cache_path}")
    print("You can now set OUTLOOK_ENABLED=true in backend/.env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
