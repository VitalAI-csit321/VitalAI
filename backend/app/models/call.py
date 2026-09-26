import enum
from datetime import date
from uuid import UUID

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, String, Text, false
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.task import TaskCategory
from app.models.triage import TriageCategory
from app.models.user import UserRole


class CallStatus(enum.StrEnum):
    RECEIVED = "received"
    PROCESSED = "processed"
    ESCALATED = "escalated"
    # Voicemail only. in_progress: in the keypad menu. recording: reached the
    # <Record> step, so a recording callback is expected even if Twilio's call
    # status callback arrives first. abandoned: ended with no recording.
    IN_PROGRESS = "in_progress"
    RECORDING = "recording"
    # Claimed by one process() run, so an overlapping run (the sweep, a
    # duplicate callback) cannot transcribe and classify the same call twice.
    PROCESSING = "processing"
    ABANDONED = "abandoned"


class CallKind(enum.StrEnum):
    LOGGED = "logged"
    VOICEMAIL = "voicemail"


# JSONB on Postgres, plain JSON on SQLite (same pattern as app/models/app_setting.py).
_jsonb = JSONB().with_variant(JSON(), "sqlite")


class Call(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "calls"

    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, name="call_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CallStatus.RECEIVED,
    )
    triage_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("triage_results.id", ondelete="SET NULL"), nullable=True, index=True
    )
    routing_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("routing_decisions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    urgency_tier: Mapped[TriageCategory | None] = mapped_column(
        SAEnum(
            TriageCategory,
            name="triage_category",
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=True,
    )
    target_queue: Mapped[str | None] = mapped_column(String(100), nullable=True)
    routing_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    category: Mapped[TaskCategory | None] = mapped_column(
        SAEnum(TaskCategory, name="task_category", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_role: Mapped[UserRole | None] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    kind: Mapped[CallKind] = mapped_column(
        SAEnum(CallKind, name="call_kind", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=CallKind.LOGGED,
        server_default=CallKind.LOGGED.value,
    )
    # The row's key while a Twilio call is live, and the idempotency key for
    # Twilio's retried callbacks.
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    twilio_recording_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # None: never on Twilio (logged call, simulated voicemail). False: a delete
    # failed and the sweep retries it.
    twilio_deleted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    audio_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    keypad_dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    keypad_intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    urgent_pressed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    transcript_quality: Mapped[dict | None] = mapped_column(_jsonb, nullable=True)
