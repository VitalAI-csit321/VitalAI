import pytest

pytestmark = pytest.mark.asyncio


async def test_list_doctors_returns_only_doctors(client, admin_headers, seeded_doctor):
    response = await client.get("/api/v1/doctors", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert any(d["id"] == str(seeded_doctor.id) for d in body)
    assert all({"id", "full_name", "department"} == set(d) for d in body)


async def test_list_doctors_filters_by_search(client, admin_headers, seeded_doctor):
    response = await client.get(
        "/api/v1/doctors", headers=admin_headers, params={"search": seeded_doctor.full_name[:4]}
    )
    assert response.status_code == 200
    assert any(d["id"] == str(seeded_doctor.id) for d in response.json())


async def test_list_doctors_allowed_for_front_desk(client, front_desk_headers):
    """Front desk books appointments, so it must be able to read the picker."""
    response = await client.get("/api/v1/doctors", headers=front_desk_headers)
    assert response.status_code == 200


async def test_list_doctors_requires_authentication(client):
    response = await client.get("/api/v1/doctors")
    assert response.status_code == 401
