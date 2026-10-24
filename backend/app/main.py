from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.db import get_engine, verify_connection_role


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    await verify_connection_role(engine)  # D-01: fail fast on an RLS-bypassing role
    yield
    await engine.dispose()


app = FastAPI(
    title="NEXIRA API",
    version="0.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
