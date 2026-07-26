from app.audit_context import get_ip_address, get_session_id, reset_audit_context, set_audit_context


def test_context_defaults_to_none():
    assert get_ip_address() is None
    assert get_session_id() is None


def test_set_and_reset_audit_context():
    ip_token, session_token = set_audit_context(ip_address="10.0.0.1", session_id="sess-abc")
    assert get_ip_address() == "10.0.0.1"
    assert get_session_id() == "sess-abc"

    reset_audit_context(ip_token, session_token)
    assert get_ip_address() is None
    assert get_session_id() is None


def test_create_access_token_includes_sid():
    from uuid import uuid4

    from app.auth.security import create_access_token, decode_access_token
    from app.models.user import UserRole

    token = create_access_token(uuid4(), UserRole.ADMIN)
    payload = decode_access_token(token)
    assert payload is not None
    assert isinstance(payload["sid"], str)
    assert len(payload["sid"]) > 0
