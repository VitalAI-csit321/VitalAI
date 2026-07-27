from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, FetchedValue, ForeignKey, String, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

# postgresql.UUID with_variant Uuid() so SQLite (local tests) still compiles
_pg_uuid = postgresql.UUID(as_uuid=True).with_variant(Uuid(), "sqlite")
# JSONB with JSON fallback for SQLite
_jsonb = JSONB().with_variant(JSON(), "sqlite")


class AuditEvent(Base):
    """Append-only audit log. UPDATE and DELETE are blocked at the DB level
    by a trigger defined in the Alembic migration. Do not edit rows from app code.
    """

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(_pg_uuid, primary_key=True, default=uuid4)
    case_id: Mapped[UUID | None] = mapped_column(
        _pg_uuid,
        ForeignKey("intake_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_id: Mapped[UUID | None] = mapped_column(
        _pg_uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    actor_label: Mapped[str] = mapped_column(String(255), nullable=False, default="system")
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(_jsonb, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    predecessor_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Server-side monotonic counter the hash-chain trigger/verify function order
    # by, instead of `timestamp` (client-assigned in Python, so its order can
    # diverge from true insert order under concurrent writers; see migration
    # 0018's docstring). Nullable here only because SQLite (no trigger, no
    # sequence default) never populates it; real Postgres rows always have it.
    sequence_number: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, server_default=FetchedValue()
    )
