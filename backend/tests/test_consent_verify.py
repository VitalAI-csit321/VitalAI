"""Staff turn a patient's online registration consent into captured consent."""

import pytest

from app.models.consent import ConsentStatus
from app.services import consent_service, patient_service, records_service
from app.services.patient_service import PromotionRefusedError

SNAPSHOT = {
    "checks": [{"label": "I agree to the clinic keeping my details.", "checked": True}],
    "signature": "data:image/png;base64,AAAA",
    "submitted_at": "2026-09-28T01:00:00+00:00",
}


@pytest.fixture
async def online(db_session, admin_user, seeded_case, patient):
    patient.is_provisional = True
    await db_session.commit()
    return await consent_service.create_consent_record(
        db_session,
        seeded_case.id,
        admin_user,
        consent_type=consent_service.ONLINE_REGISTRATION,
        form_snapshot=SNAPSHOT,
    )


async def test_verify_captures_it_and_keeps_what_the_patient_signed(
    client, admin_headers, admin_user, online
):
    response = await client.post(f"/api/v1/consent/{online.id}/verify", headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "captured"
    assert body["form_snapshot"]["signature"] == SNAPSHOT["signature"]
    assert body["form_snapshot"]["checks"] == SNAPSHOT["checks"]


async def test_pending_online_consent_unlocks_nothing_until_verified(
    db_session, admin_user, patient, online
):
    with pytest.raises(PromotionRefusedError):
        await patient_service.promote_patient(db_session, patient.id, admin_user)
    assert await records_service.has_explicit_consent(db_session, patient.id) is False

    await consent_service.verify_online_consent(db_session, online.id, admin_user)

    await db_session.refresh(online)
    assert online.form_snapshot["verified_by"] == str(admin_user.id)
    assert await records_service.has_explicit_consent(db_session, patient.id) is True
    promoted = await patient_service.promote_patient(db_session, patient.id, admin_user)
    assert promoted.is_provisional is False


async def test_only_a_pending_signed_online_consent_can_be_verified(
    client, admin_headers, admin_user, db_session, seeded_case, online
):
    staff = await consent_service.create_consent_record(
        db_session, seeded_case.id, admin_user, consent_type="general_treatment"
    )
    unsigned = await consent_service.create_consent_record(
        db_session,
        seeded_case.id,
        admin_user,
        consent_type=consent_service.ONLINE_REGISTRATION,
        form_snapshot={"checks": [], "signature": ""},
    )
    await client.post(f"/api/v1/consent/{online.id}/verify", headers=admin_headers)

    for record in (staff, unsigned, online):
        response = await client.post(f"/api/v1/consent/{record.id}/verify", headers=admin_headers)
        assert response.status_code == 409


async def test_verify_unknown_is_404_and_doctors_may_not(
    client, admin_headers, doctor_headers, online
):
    missing = await client.post(
        "/api/v1/consent/00000000-0000-0000-0000-000000000000/verify", headers=admin_headers
    )
    doctor = await client.post(f"/api/v1/consent/{online.id}/verify", headers=doctor_headers)

    assert missing.status_code == 404
    assert doctor.status_code == 403
    assert online.status == ConsentStatus.PENDING
