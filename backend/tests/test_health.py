from httpx import AsyncClient


async def test_health_ok(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["synthetic_only"] is True


async def test_health_carries_the_clinic_timezone(client: AsyncClient):
    # The calendar UI treated clinic time as UTC: an "11:00" booking was
    # stored as 10pm Sydney. It reads the zone from here (every role can).
    response = await client.get("/health")

    assert response.json()["clinic_timezone"] == "Australia/Sydney"
