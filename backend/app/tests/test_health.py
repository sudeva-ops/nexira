from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.main import app, create_app


async def test_health_returns_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def status_of(api: FastAPI, method: str, path: str) -> int:
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        return (await client.request(method, path)).status_code


async def test_a_pilot_has_no_scenario_api_and_no_api_docs() -> None:
    pilot, demo = create_app("pilot"), create_app("demo")
    assert await status_of(pilot, "GET", "/api/incidents") == 401  # there, needs a token
    assert await status_of(pilot, "POST", "/api/scenarios/NBO-CIVIL-UNREST/reset") == 404  # D-21
    assert await status_of(pilot, "GET", "/api/docs") == 404
    assert await status_of(pilot, "GET", "/api/openapi.json") == 404
    assert await status_of(demo, "POST", "/api/scenarios/NBO-CIVIL-UNREST/reset") == 401
    assert await status_of(demo, "GET", "/api/docs") == 200


def test_every_api_operation_but_health_needs_a_bearer_token() -> None:
    """Deny by default (ASVS 4.1.5): a new route without the auth dependency fails here."""
    schema = create_app("demo").openapi()
    open_operations = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if not operation.get("security") and path != "/api/health"
    ]
    assert open_operations == []
    assert len(schema["paths"]) > 30
