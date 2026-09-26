import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import bcrypt
from jose import JWTError, jwt

from app.config import settings
from app.schemas.enums import UserRole

# bcrypt has a hard 72-byte input limit. Pre-truncate.
_BCRYPT_MAX_BYTES = 72


def _to_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_to_bytes(password), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_to_bytes(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: UUID, role: UserRole) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "sid": str(uuid4()),
        "exp": int(expire.timestamp()),
    }
    encoded: str = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded


def decode_access_token(token: str) -> dict[str, object] | None:
    try:
        decoded: dict[str, object] = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return decoded
    except JWTError:
        return None


# Password reset tokens. No "sub" claim, so get_current_user can never accept
# one as an access token. "pwh" binds the token to the current password hash:
# once the password changes, every outstanding reset link stops working.
_RESET_TOKEN_MINUTES = 30


def _password_fingerprint(hashed_password: str) -> str:
    return hashlib.sha256(hashed_password.encode("utf-8")).hexdigest()[:16]


def create_password_reset_token(user_id: UUID, hashed_password: str) -> str:
    expire = datetime.now(UTC) + timedelta(minutes=_RESET_TOKEN_MINUTES)
    payload = {
        "rst": str(user_id),
        "pwh": _password_fingerprint(hashed_password),
        "exp": int(expire.timestamp()),
    }
    encoded: str = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded


def read_password_reset_token(token: str) -> UUID | None:
    """User id the token was issued for, or None if it is invalid or expired.

    The caller must still call reset_token_matches() against the user's
    current hash, which is what makes the token single-use.
    """
    payload = decode_access_token(token)
    if payload is None or not isinstance(payload.get("rst"), str):
        return None
    try:
        return UUID(str(payload["rst"]))
    except ValueError:
        return None


def reset_token_matches(token: str, hashed_password: str) -> bool:
    payload = decode_access_token(token)
    return payload is not None and payload.get("pwh") == _password_fingerprint(hashed_password)
