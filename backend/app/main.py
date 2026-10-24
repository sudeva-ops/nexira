from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.db import get_engine, verify_connection_role
from app.modules.audit.router import router as audit_router
from app.modules.scenarios.router import router as scenarios_router
from app.modules.scenarios.service import registry
from app.modules.tenancy.router import router as tenancy_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: fail fast on an RLS-bypassing role
    yield
    await registry.close()
    await engine.dispose()


app = FastAPI(
    title="NEXIRA API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


app.include_router(tenancy_router)
app.include_router(audit_router)
app.include_router(scenarios_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
