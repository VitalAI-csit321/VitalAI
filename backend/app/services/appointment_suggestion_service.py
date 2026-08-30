"""Propose appointment slots. Never books one.

RBAC report section 11, invariant 2: "AI never commits appointments. Suggest
only; a human accepts." That is enforced structurally here, not by convention:
this module can only write AppointmentStatus.PENDING, and pending rows are
excluded from the excl_doctor_overlap constraint (ADR-003), so a suggestion
never removes a slot from anyone else's calendar.

Contention resolves at accept time: confirming a suggestion whose slot was
taken raises the exclusion constraint and surfaces as a 409, which the
New/Edit pages already render.
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.appointment import Appointment, AppointmentStatus, AppointmentType
from app.models.user import User
from app.services import appointment_service
from app.services.audit_service import record_event


async def suggest_slots(
    db: AsyncSession,
    actor: User,
    case_id: UUID,
    doctor_id: UUID,
    from_date: date,
    count: int = 3,
    duration_minutes: int = 30,
    search_days: int = 14,
) -> list[Appointment]:
    """Walk forward from from_date and write the first `count` free slots as
    pending suggestions. Returns fewer than `count` if the window has fewer.
    """
    suggestions: list[Appointment] = []

    for offset in range(search_days):
        if len(suggestions) >= count:
            break
        day = from_date + timedelta(days=offset)
        if day.weekday() >= 5:
            continue

        availability = await appointment_service.get_availability(
            db, actor, doctor_id, day, duration_minutes
        )
        for slot in availability.slots:
            if len(suggestions) >= count:
                break
            if not slot.available:
                continue
            appointment = Appointment(
                doctor_id=doctor_id,
                case_id=case_id,
                time_slot=slot.start,
                duration_minutes=duration_minutes,
                appointment_type=AppointmentType.OTHER,
                # The only status this module may ever write.
                status=AppointmentStatus.PENDING,
                reference_code=await appointment_service._generate_unique_reference_code(db),
            )
            db.add(appointment)
            await db.flush()
            suggestions.append(appointment)

    for appointment in suggestions:
        await record_event(
            db,
            case_id=case_id,
            actor=actor,
            action="appointment.suggested",
            details={
                "appointment_id": str(appointment.id),
                "doctor_id": str(doctor_id),
                "time_slot": appointment.time_slot.isoformat(),
            },
        )

    await db.commit()
    for appointment in suggestions:
        await db.refresh(appointment)
    return suggestions
