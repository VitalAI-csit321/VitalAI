"""Staff turn a patient's online registration consent into captured consent."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.consent import ConsentStatus
from app.models.human_review import HumanReviewTask
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


async def test_by_case_can_open_a_named_consent_not_only_the_latest(
    client, admin_headers, admin_user, db_session, seeded_case, online
):
    # The queue lists every record; "Verify ID" must open that one even when
    # a later consent exists on the same case.
    later = await consent_service.create_consent_record(
        db_session, seeded_case.id, admin_user, consent_type="general_treatment"
    )
    url = f"/api/v1/consent/by-case/{seeded_case.id}"

    latest = await client.get(url, headers=admin_headers)
    named = await client.get(url, params={"consent_id": str(online.id)}, headers=admin_headers)
    elsewhere = await client.get(
        f"/api/v1/consent/by-case/{uuid4()}",
        params={"consent_id": str(online.id)},
        headers=admin_headers,
    )
    wrong = await client.get(url, params={"consent_id": str(uuid4())}, headers=admin_headers)

    assert latest.json()["id"] == str(later.id)
    assert named.json()["id"] == str(online.id)
    assert elsewhere.status_code == 404
    assert wrong.status_code == 404


SIGNED = "data:image/png;base64,BBBB"


@pytest.fixture
async def unfinished(db_session, admin_user, seeded_case):
    """An online consent the patient left part done and unsigned."""
    return await consent_service.create_consent_record(
        db_session,
        seeded_case.id,
        admin_user,
        consent_type=consent_service.ONLINE_REGISTRATION,
        form_snapshot={
            "checks": [
                {"label": "I agree to the clinic keeping my details.", "checked": True},
                {"label": "I have read and understood the consent form", "checked": False},
            ],
            "signature": None,
        },
    )


async def test_staff_finish_an_unfinished_online_consent_at_the_clinic(
    client, admin_headers, admin_user, db_session, unfinished
):
    response = await client.post(
        f"/api/v1/consent/{unfinished.id}/verify",
        json={"checks": [True, True], "signature": SIGNED},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "captured"
    assert body["form_snapshot"]["signature"] == SIGNED
    assert [c["checked"] for c in body["form_snapshot"]["checks"]] == [True, True]
    assert body["form_snapshot"]["checks"][1]["label"] == (
        "I have read and understood the consent form"
    )
    await db_session.refresh(unfinished)
    assert unfinished.form_snapshot["verified_by"] == str(admin_user.id)


async def test_a_box_still_unticked_at_the_clinic_goes_to_review(
    client, admin_headers, db_session, seeded_case, unfinished
):
    response = await client.post(
        f"/api/v1/consent/{unfinished.id}/verify",
        json={"checks": [True, False], "signature": SIGNED},
        headers=admin_headers,
    )

    assert response.status_code == 200
    reviews = (
        (
            await db_session.execute(
                select(HumanReviewTask).where(HumanReviewTask.case_id == seeded_case.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(reviews) == 1  # the clinic's own rule for an incomplete consent


@pytest.mark.parametrize(
    "body",
    [
        None,  # still no signature anywhere
        {"checks": [True], "signature": SIGNED},  # one answer per statement
    ],
)
async def test_verify_refuses_an_unsigned_or_misshapen_completion(
    client, admin_headers, unfinished, body
):
    response = await client.post(
        f"/api/v1/consent/{unfinished.id}/verify", json=body, headers=admin_headers
    )

    assert response.status_code == 409


async def test_an_unsigned_online_consent_can_be_opened(
    client, admin_headers, seeded_case, unfinished
):
    # Unsigned online, or blanked by the purge: the view page must still load it.
    response = await client.get(
        f"/api/v1/consent/by-case/{seeded_case.id}",
        params={"consent_id": str(unfinished.id)},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json()["form_snapshot"]["signature"] is None
