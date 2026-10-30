"""Current conditions per mission (WX-01; plan G-7: every role reads them, like missions)."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.approvals import require_roles
from app.core.security import CurrentUser, get_db
from app.modules.tenancy.service import ROLES
from app.modules.weather.feed import STALE_AFTER
from app.modules.weather.schemas import WeatherOut

router = APIRouter(prefix="/api", tags=["weather"])

Reader = Annotated[CurrentUser, Depends(require_roles(*ROLES))]
Db = Annotated[AsyncSession, Depends(get_db)]

_CURRENT = text(
    """
    SELECT m.id AS mission_id, m.code AS mission_code, m.city, m.country_code,
           ST_Y(m.location::geometry) AS lat, ST_X(m.location::geometry) AS lon,
           w.observed_at, w.temperature_c, w.condition, w.wind_kph, w.gust_kph, w.rain_mm,
           w.source
      FROM weather_current w JOIN mission m ON m.id = w.mission_id
     ORDER BY m.code
    """
)


@router.get("/weather")
async def list_weather(_user: Reader, session: Db) -> list[WeatherOut]:
    now = datetime.now(UTC)
    return [
        WeatherOut(**row._mapping, stale=now - row.observed_at > STALE_AFTER)
        for row in await session.execute(_CURRENT)
    ]
