"""Make the first admin account, or make an existing account an admin.

POST /auth/register needs a logged-in admin, so on a fresh installation the
first admin is made here, by someone with a shell on the server. Audited like
any other account change.

Usage (on the expo box):
    docker compose -f docker-compose.prod.yml exec api \\
        python -m scripts.create_admin you@example.com "Your Name"
It asks for a password when the account is new. An existing account keeps its
password and only becomes an admin.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import hash_password
from app.models.user import User, UserRole
from app.schemas.auth import UserRegister
from app.services import audit_service


async def run(db: AsyncSession, *, email: str, full_name: str, password: str | None) -> User:
    """Create an admin, or promote the account with this email. ValueError on bad input."""
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        try:
            checked = UserRegister(email=email, password=password or "", full_name=full_name)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        user = User(
            email=checked.email,
            hashed_password=hash_password(checked.password),
            full_name=checked.full_name,
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.flush()
        action = "user.created"
        details = {"user_id": str(user.id), "role": UserRole.ADMIN.value}
    else:
        old_role = user.role
        user.role = UserRole.ADMIN
        await db.flush()
        action = "user.role_changed"
        details = {
            "user_id": str(user.id),
            "old_role": old_role.value,
            "new_role": UserRole.ADMIN.value,
        }
    await audit_service.record_event(
        db, actor=user, action=action, details=details | {"via": "scripts.create_admin"}
    )
    await db.commit()
    return user


async def main() -> None:
    from app.database import AsyncSessionLocal

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    parser.add_argument("full_name")
    args = parser.parse_args()

    async with AsyncSessionLocal() as db:
        password = None
        if await db.scalar(select(User.id).where(User.email == args.email)) is None:
            password = getpass.getpass("Password (8 or more characters): ")
            if password != getpass.getpass("Same password again: "):
                raise SystemExit("The passwords differ. Nothing changed.")
        try:
            user = await run(db, email=args.email, full_name=args.full_name, password=password)
        except ValueError as exc:
            raise SystemExit(f"Nothing changed: {exc}") from exc
    print(
        f"{user.email} is an admin. Log in on the site; log out and in again if already signed in."
    )


if __name__ == "__main__":
    asyncio.run(main())
