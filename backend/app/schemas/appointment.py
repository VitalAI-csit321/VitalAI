from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.appointment import AppointmentStatus, AppointmentType


class AppointmentRepeat(BaseModel):
    interval_days: int = Field(gt=0)
    occurrences: int = Field(gt=1, le=52)


class AppointmentCreate(BaseModel):
    doctor_id: UUID
    case_id: UUID
    time_slot: datetime
    # gt=0 mirrors the DB CHECK. Validating at both layers is deliberate:
    # this is a trust boundary (F4, F5).
    duration_minutes: int = Field(default=30, gt=0, le=480)
    appointment_type: AppointmentType = AppointmentType.OTHER
    location: str | None = Field(default=None, max_length=255)
    reason: str | None = None
    internal_notes: str | None = None
    status: AppointmentStatus = AppointmentStatus.CONFIRMED
    notify_patient: bool = True
    notify_provider: bool = True
    repeat: AppointmentRepeat | None = None

    @field_validator("status")
    @classmethod
    def _status_must_be_creatable(cls, v: AppointmentStatus) -> AppointmentStatus:
        # completed/cancelled are reached via complete_appointment/cancel_appointment,
        # which enforce their own state guards (e.g. only a CONFIRMED appointment
        # can be completed) and the overlap constraint (0026) only covers
        # confirmed/completed rows -- creating straight into either state on POST
        # would bypass both.
        if v not in (AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED):
            raise ValueError("New appointments can only be created as pending or confirmed")
        return v


class AppointmentUpdate(BaseModel):
    doctor_id: UUID | None = None
    time_slot: datetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=480)
    appointment_type: AppointmentType | None = None
    location: str | None = Field(default=None, max_length=255)
    reason: str | None = None
    internal_notes: str | None = None
    status: AppointmentStatus | None = None
    notify_patient: bool | None = None
    notify_provider: bool | None = None
    reschedule_reason: str | None = None


class AppointmentCancel(BaseModel):
    cancel_reason: str | None = None
    notify_patient: bool = True


class AppointmentReschedule(BaseModel):
    time_slot: datetime


class AppointmentOut(BaseModel):
    id: UUID
    case_id: UUID
    doctor_id: UUID
    time_slot: datetime
    end_time: datetime
    duration_minutes: int
    appointment_type: AppointmentType
    location: str | None
    reason: str | None
    internal_notes: str | None
    status: AppointmentStatus
    reference_code: str
    notify_patient: bool
    notify_provider: bool
    series_id: UUID | None
    created_at: datetime
    updated_at: datetime
    doctor_name: str | None
    patient_name: str | None
    patient_mrn: str | None


class AppointmentListResponse(BaseModel):
    items: list[AppointmentOut]
    total: int


class AppointmentPatientSummary(BaseModel):
    id: UUID | None
    mrn: str | None
    name: str
    dob: str | None
    gender: str | None


class AppointmentConsentSummary(BaseModel):
    status: str
    captured_at: datetime | None


class AppointmentHistoryEntry(BaseModel):
    action: str
    label: str
    actor_label: str | None
    timestamp: datetime
    details: dict


class AppointmentDetailOut(AppointmentOut):
    patient: AppointmentPatientSummary | None
    consent: AppointmentConsentSummary | None
    history: list[AppointmentHistoryEntry]


class CalendarStats(BaseModel):
    scheduled: int
    pending_confirmation: int
    confirmed_today: int
    cancellations: int


class CalendarDayCell(BaseModel):
    date: str
    appointments: list[AppointmentOut]
    total: int


class CalendarMonthOut(BaseModel):
    year: int
    month: int
    stats: CalendarStats
    days: list[CalendarDayCell]


class CalendarMarkerOut(BaseModel):
    date: str
    count: int


class ProviderDayLoad(BaseModel):
    doctor_id: UUID
    doctor_name: str
    appointment_count: int


class DayViewOut(BaseModel):
    date: str
    stats: CalendarStats
    appointments: list[AppointmentOut]
    total_booked_minutes: int
    status_breakdown: dict[str, int]
    providers: list[ProviderDayLoad]


class AvailabilitySlotOut(BaseModel):
    start: datetime
    end: datetime
    available: bool


class AvailabilityOut(BaseModel):
    doctor_id: UUID
    date: str
    slot_minutes: int
    slots: list[AvailabilitySlotOut]


class AppointmentSuggestRequest(BaseModel):
    case_id: UUID
    doctor_id: UUID
    from_date: date
    count: int = Field(default=3, ge=1, le=5)
    duration_minutes: int = Field(default=30, gt=0, le=480)
    search_days: int = Field(default=14, ge=1, le=60)
