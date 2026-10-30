import uuid
from datetime import datetime

from pydantic import BaseModel


class WeatherOut(BaseModel):
    mission_id: uuid.UUID
    mission_code: str
    city: str
    country_code: str
    lat: float
    lon: float
    observed_at: datetime
    temperature_c: float
    condition: str
    wind_kph: int
    gust_kph: int
    rain_mm: float
    source: str
    stale: bool  # older than 30 minutes (WX §28 Q2, plan G-6)
