"""Silent-only token refresh.

The security property under test: this module must never block on an
interactive device flow, because it runs inside a request/poll path. A missing
or lapsed cache is an error, not a prompt.
"""

import pytest

from app.services import outlook_auth
from app.services.outlook_auth import OutlookAuthRequiredError


class _FakeApp:
    def __init__(self, accounts=None, silent_result=None):
        self._accounts = accounts if accounts is not None else []
        self._silent_result = silent_result

    def get_accounts(self):
        return self._accounts

    def acquire_token_silent(self, scopes, account=None):
        return self._silent_result


@pytest.mark.asyncio
async def test_returns_token_when_cache_has_an_account(monkeypatch):
    monkeypatch.setattr(
        outlook_auth,
        "build_app",
        lambda cache: _FakeApp(
            accounts=[{"username": "a@b.c"}], silent_result={"access_token": "tok"}
        ),
    )
    monkeypatch.setattr(outlook_auth, "save_cache", lambda cache: None)

    assert await outlook_auth.get_access_token() == "tok"


@pytest.mark.asyncio
async def test_no_cached_account_raises_rather_than_prompting(monkeypatch):
    monkeypatch.setattr(outlook_auth, "build_app", lambda cache: _FakeApp(accounts=[]))
    monkeypatch.setattr(outlook_auth, "save_cache", lambda cache: None)

    with pytest.raises(OutlookAuthRequiredError, match="outlook_login"):
        await outlook_auth.get_access_token()


@pytest.mark.asyncio
async def test_expired_refresh_token_raises(monkeypatch):
    """acquire_token_silent returns None once the refresh token itself lapses."""
    monkeypatch.setattr(
        outlook_auth,
        "build_app",
        lambda cache: _FakeApp(accounts=[{"username": "a@b.c"}], silent_result=None),
    )
    monkeypatch.setattr(outlook_auth, "save_cache", lambda cache: None)

    with pytest.raises(OutlookAuthRequiredError, match="could not be refreshed"):
        await outlook_auth.get_access_token()


@pytest.mark.asyncio
async def test_result_without_access_token_raises(monkeypatch):
    monkeypatch.setattr(
        outlook_auth,
        "build_app",
        lambda cache: _FakeApp(
            accounts=[{"username": "a@b.c"}], silent_result={"error": "invalid_grant"}
        ),
    )
    monkeypatch.setattr(outlook_auth, "save_cache", lambda cache: None)

    with pytest.raises(OutlookAuthRequiredError):
        await outlook_auth.get_access_token()


def test_scopes_cover_read_write_and_send():
    """Matthew's original requested Mail.Read only, which is why its
    mark_as_read call 403s. Both extra scopes are load-bearing here."""
    assert "Mail.ReadWrite" in outlook_auth.SCOPES
    assert "Mail.Send" in outlook_auth.SCOPES


def test_cache_file_is_written_owner_only(tmp_path, monkeypatch):
    """The cache holds a live refresh token."""
    path = tmp_path / "cache.json"
    monkeypatch.setattr(outlook_auth.settings, "outlook_token_cache_path", str(path))

    class _Cache:
        has_state_changed = True

        def serialize(self):
            return "{}"

    outlook_auth.save_cache(_Cache())
    assert path.exists()
    assert path.stat().st_mode & 0o777 == 0o600
