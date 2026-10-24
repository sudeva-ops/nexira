from fastapi import FastAPI

app = FastAPI(
    title="NEXIRA API", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
