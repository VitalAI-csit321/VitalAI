"""Microsoft Graph token acquisition for the inbound mail connector.

Ported from Matthew's Inbox_Handling/Outlook_Authentication.py, split in two:
the interactive device-code flow lives in scripts/outlook_login.py and runs
once by hand, while this module only ever refreshes silently from the cache
that script wrote. The split exists because a device-code flow blocks on a
human visiting a URL, which a FastAPI process serving requests can never do.

The token cache file holds a live refresh token. It is gitignored and must
stay that way.
"""

from __future__ import annotations

import logging
from pathlib import Path

from msal import PublicClientApplication, SerializableTokenCache

from app.config import settings

logger = logging.getLogger(__name__)

# Mail.ReadWrite (not Matthew's Mail.Read) because the connector marks messages
# read after ingesting them, and Mail.Send because an approved draft reply is
# sent through Graph. Requesting Mail.Read alone is why mark_as_read returns 403
# in the original script.
SCOPES = ["Mail.ReadWrite", "Mail.Send"]


class OutlookAuthRequiredError(Exception):
    """No usable cached token: a human must re-run scripts/outlook_login.py.

    Distinct from a transport or Graph error so the poller can log it as an
    action-needed condition rather than retrying it as a transient fault.
    """


def load_cache() -> SerializableTokenCache:
    cache = SerializableTokenCache()
    path = Path(settings.outlook_token_cache_path)
    if path.exists():
        cache.deserialize(path.read_text())
    return cache


def save_cache(cache: SerializableTokenCache) -> None:
    if not cache.has_state_changed:
        return
    path = Path(settings.outlook_token_cache_path)
    path.write_text(cache.serialize())
    # Refresh token on disk: keep it owner-only, the same reasoning that keeps
    # it out of git.
    path.chmod(0o600)


def build_app(cache: SerializableTokenCache) -> PublicClientApplication:
    return PublicClientApplication(
        settings.outlook_client_id,
        authority=settings.outlook_authority,
        token_cache=cache,
    )


async def get_access_token() -> str:
    """Return a valid access token, refreshing silently from the cache.

    Never initiates a device flow: that is scripts/outlook_login.py's job.
    Raises OutlookAuthRequiredError when no account is cached or the refresh
    token has expired, which is a human-action condition, not a retryable one.
    """
    cache = load_cache()
    app = build_app(cache)

    accounts = app.get_accounts()
    if not accounts:
        raise OutlookAuthRequiredError(
            "No cached Outlook account. Run: python scripts/outlook_login.py"
        )

    # acquire_token_silent uses the cached refresh token when the access token
    # has expired; it returns None once that refresh token itself lapses.
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    save_cache(cache)

    if not result or "access_token" not in result:
        raise OutlookAuthRequiredError(
            "Cached Outlook token could not be refreshed (expired or revoked). "
            "Run: python scripts/outlook_login.py"
        )
    return str(result["access_token"])
