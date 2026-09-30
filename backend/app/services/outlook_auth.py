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
import time
from pathlib import Path
from uuid import UUID

from msal import PublicClientApplication, SerializableTokenCache, TokenCache

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


def connected_account() -> str | None:
    """The signed-in mailbox, read straight from the cache (no network)."""
    accounts = load_cache().find(TokenCache.CredentialType.ACCOUNT)
    return accounts[0].get("username") if accounts else None


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


# "Sign in with Microsoft" from Settings: the auth-code flow with PKCE, which a
# public client may use once its redirect URI is registered in Azure (Mobile and
# desktop platform). Pending sign-ins are keyed by the OAuth state.
# ponytail: process-local; a sign-in must finish on the worker that started it.
# Move to Redis if the API ever runs more than one worker.
SIGN_IN_TTL_SECONDS = 600
_pending: dict[str, tuple[dict, UUID, float]] = {}


def start_sign_in(redirect_uri: str, user_id: UUID) -> str:
    flow = build_app(load_cache()).initiate_auth_code_flow(
        SCOPES, redirect_uri=redirect_uri, login_hint=settings.outlook_mailbox_address or None
    )
    _pending[flow["state"]] = (flow, user_id, time.monotonic())
    return flow["auth_uri"]


def finish_sign_in(params: dict[str, str]) -> tuple[UUID, str]:
    """Complete a sign-in from Microsoft's redirect; returns (who started it, mailbox).

    Raises OutlookAuthRequiredError for an unknown, replayed, expired, cancelled
    or failed sign-in. The state is single use: it is removed before anything else.
    """
    entry = _pending.pop(params.get("state", ""), None)
    if entry is None or time.monotonic() - entry[2] > SIGN_IN_TTL_SECONDS:
        raise OutlookAuthRequiredError("Unknown or expired sign-in")
    flow, user_id, _ = entry
    # A fresh cache, so the mailbox just signed in is the only account the
    # poller can pick up.
    cache = SerializableTokenCache()
    result = build_app(cache).acquire_token_by_auth_code_flow(flow, params)
    if "access_token" not in result:
        raise OutlookAuthRequiredError(
            result.get("error_description") or result.get("error", "Sign-in failed")
        )
    save_cache(cache)
    return user_id, result.get("id_token_claims", {}).get("preferred_username", "")


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
