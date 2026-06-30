from httpx import AsyncClient


async def _create_case(client: AsyncClient, headers: dict) -> str:
    response = await client.post(
        "/api/v1/intake",
        json={
            "patient_name": "Consent Tester",
            "contact_reason": "Visit",
            "contact_channel": "phone",
        },
        headers=headers,
    )
    return response.json()["id"]


async def test_consent_capture_flow(client: AsyncClient, admin_headers: dict):
    case_id = await _create_case(client, admin_headers)

    create = await client.post(
        "/api/v1/consent",
        json={"case_id": case_id},
        headers=admin_headers,
    )
    assert create.status_code == 201
    consent_id = create.json()["id"]
    assert create.json()["status"] == "pending"

    capture = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert capture.status_code == 200
    assert capture.json()["status"] == "captured"
    assert capture.json()["captured_at"] is not None


async def test_consent_capture_twice_returns_409(client: AsyncClient, admin_headers: dict):
    case_id = await _create_case(client, admin_headers)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    first = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert first.status_code == 200

    second = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert second.status_code == 409


async def test_consent_withdraw_after_capture(client: AsyncClient, admin_headers: dict):
    case_id = await _create_case(client, admin_headers)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    withdraw = await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    assert withdraw.status_code == 200
    assert withdraw.json()["status"] == "withdrawn"


async def test_consent_withdraw_then_capture_blocked(client: AsyncClient, admin_headers: dict):
    case_id = await _create_case(client, admin_headers)
    create = await client.post("/api/v1/consent", json={"case_id": case_id}, headers=admin_headers)
    consent_id = create.json()["id"]

    await client.post(f"/api/v1/consent/{consent_id}/withdraw", headers=admin_headers)
    capture = await client.post(f"/api/v1/consent/{consent_id}/capture", headers=admin_headers)
    assert capture.status_code == 409
