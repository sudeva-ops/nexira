from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core import errors
from app.core.db import get_engine, verify_connection_role
from app.core.realtime import hub
from app.core.realtime import router as realtime_router
from app.modules.audit.router import router as audit_router
from app.modules.checkin.router import router as checkin_router
from app.modules.intel.router import router as intel_router
from app.modules.notifications.router import router as notifications_router
from app.modules.people.router import router as people_router
from app.modules.playbooks.router import router as playbooks_router
from app.modules.scenarios.router import router as scenarios_router
from app.modules.scenarios.service import registry
from app.modules.tenancy.router import router as tenancy_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: fail fast on an RLS-bypassing role
    yield
    await hub.close()
    await registry.close()
    await engine.dispose()


app = FastAPI(
    title="NEXIRA API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
errors.install(app)


app.include_router(tenancy_router)
app.include_router(audit_router)
app.include_router(scenarios_router)
app.include_router(intel_router)
app.include_router(people_router)
app.include_router(playbooks_router)
app.include_router(notifications_router)
app.include_router(checkin_router)
app.include_router(realtime_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
