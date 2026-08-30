from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, utcnow

# JSONB on Postgres, plain JSON on SQLite. Same pattern as app/models/audit.py:
# SQLite tests build schema from Base.metadata.create_all and cannot compile JSONB.
_jsonb = JSONB().with_variant(JSON(), "sqlite")


class AppSetting(Base):
    """A runtime override for one key in app/config.py's Settings.

    `value` wraps the real value as {"v": ...} so one JSON column can hold a
    bool, number, string, list or dict without a per-type column.

    Nothing here is trusted. SETTINGS_REGISTRY in app/services/settings_service.py
    is the sole validation boundary; a row whose key is not in the registry is
    ignored on hydrate.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(_jsonb, nullable=False)
    updated_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
