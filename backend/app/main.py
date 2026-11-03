from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import errors
from app.core.config import get_settings
from app.core.db import get_engine, verify_connection_role
from app.core.realtime import hub
from app.core.realtime import router as realtime_router
from app.modules.agents.router import router as agents_router
from app.modules.audit.router import router as audit_router
from app.modules.checkin.router import router as checkin_router
from app.modules.documents.router import router as documents_router
from app.modules.evacuations.router import router as evacuations_router
from app.modules.executive.router import router as executive_router
from app.modules.fleet.router import router as fleet_router
from app.modules.hazards.router import router as hazards_router
from app.modules.health_intel.router import router as health_router
from app.modules.intel.router import router as intel_router
from app.modules.notifications.router import router as notifications_router
from app.modules.partners.router import router as partners_router
from app.modules.people.router import router as people_router
from app.modules.playbooks.router import router as playbooks_router
from app.modules.predictive.router import router as predictive_router
from app.modules.scenarios.router import router as scenarios_router
from app.modules.scenarios.service import registry
from app.modules.supply.router import router as supply_router
from app.modules.tenancy.router import router as tenancy_router
from app.modules.travel.router import router as travel_router
from app.modules.twin.router import router as twin_router
from app.modules.vip.router import router as vip_router
from app.modules.weather.router import router as weather_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: fail fast on an RLS-bypassing role
    yield
    await hub.close()
    await registry.close()
    await engine.dispose()


# D-21: the scenario player (presenter bar) and its reset exist for demos only.
DEMO_ENVS = frozenset({"local", "demo", "test"})


def create_app(app_env: str) -> FastAPI:
    """The API. A pilot has no scenario API and no interactive API docs."""
    demo = app_env in DEMO_ENVS
    api = FastAPI(
        title="NEXIRA API",
        version="0.1.0",
        docs_url="/api/docs" if demo else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if demo else None,
        lifespan=lifespan,
    )
    errors.install(api)
    for router in (
        tenancy_router,
        audit_router,
        intel_router,
        people_router,
        playbooks_router,
        notifications_router,
        partners_router,
        documents_router,
        hazards_router,
        health_router,
        evacuations_router,
        fleet_router,
        vip_router,
        twin_router,
        supply_router,
        executive_router,
        predictive_router,
        checkin_router,
        agents_router,
        travel_router,
        weather_router,
        realtime_router,
    ):
        api.include_router(router)
    if demo:
        api.include_router(scenarios_router)
    api.add_api_route("/api/health", health)
    return api


async def health() -> dict[str, str]:
    return {"status": "ok"}


app = create_app(get_settings().app_env)
