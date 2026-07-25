"""Request-scoped context for audit enrichment (IP address, session id).

record_event() reads these as defaults so IP/session capture doesn't
require threading a Request object through its sixteen call sites across
services, routes, and dependencies. Populated once per request by the
middleware in app/main.py.
"""

from contextvars import ContextVar, Token

_ip_address: ContextVar[str | None] = ContextVar("audit_ip_address", default=None)
_session_id: ContextVar[str | None] = ContextVar("audit_session_id", default=None)


def get_ip_address() -> str | None:
    return _ip_address.get()


def get_session_id() -> str | None:
    return _session_id.get()


def set_audit_context(*, ip_address: str | None, session_id: str | None) -> tuple[Token, Token]:
    ip_token = _ip_address.set(ip_address)
    session_token = _session_id.set(session_id)
    return ip_token, session_token


def reset_audit_context(ip_token: Token, session_token: Token) -> None:
    _ip_address.reset(ip_token)
    _session_id.reset(session_token)
