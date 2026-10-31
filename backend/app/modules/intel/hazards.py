"""Natural hazards as intelligence (HZ-01, HZ-02, D-38; docs/plan-pilot-hz.md §2, §3).

Severity, size and fusion window per hazard category. Signals of a measured category
(EARTHQUAKE, TROPICAL_CYCLONE, AIR_QUALITY) carry a typed "hazard" object in their
payload; the measure decides the severity, never the source's severity_map, and a
missing or out-of-range measure discards the signal (nothing is guessed). WILDFIRE is
MODERATE; exposure raises it to HIGH when a mission site is inside its 20 km (G-4).
Weather's categories keep their sizes (WX-04). Everything else keeps 3 km / 5 km and
the 60-minute window, so D-23 does not move.
"""

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

FUSION_RADIUS_M = 3_000
IMPACT_RADIUS_M = 5_000  # the schema default (incident.impact_radius_m)
FUSION_WINDOW_MIN = 60
# WX §28 Q4 (plan-pilot-wx.md §3): impact radius = fusion distance for weather.
WEATHER_SIZES = {"STORM": 60_000, "FLOOD": 25_000, "DUST_STORM": 40_000, "EXTREME_HEAT": 30_000}
# §43 Q3: fixed sizes; an earthquake's comes from its magnitude.
HAZARD_SIZES = {"TROPICAL_CYCLONE": 150_000, "AIR_QUALITY": 30_000, "WILDFIRE": 20_000}
# G-3: slow hazards are reported hours apart and stay one incident.
FUSION_WINDOWS_MIN = {"TROPICAL_CYCLONE": 48 * 60, "AIR_QUALITY": 24 * 60, "WILDFIRE": 24 * 60}

# The six categories of the Natural Hazards screen (HZ-09).
HAZARD_CATEGORIES = (
    "EARTHQUAKE",
    "TROPICAL_CYCLONE",
    "FLOOD",
    "EXTREME_HEAT",
    "WILDFIRE",
    "AIR_QUALITY",
)
CATEGORY_LABELS = {
    "TROPICAL_CYCLONE": "Tropical cyclone",
    "AIR_QUALITY": "Air quality",
    "EXTREME_HEAT": "Extreme heat",
}
WILDFIRE_SEVERITY = "MODERATE"  # raised to HIGH by exposure (G-4)
LANDFALL_LEAD_H = 36  # §43 Q4: an armed playbook starts 36 h before landfall
NO_MISSION_WITHIN_M = 300_000  # HZ-03
FUTURE_TOLERANCE = timedelta(minutes=10)  # a hazard signal dated later is discarded


class _Measure(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Earthquake(_Measure):
    magnitude: float = Field(ge=0, le=10)
    depth_km: float = Field(default=10, ge=0, le=700)


class Cyclone(_Measure):
    cyclone_category: int = Field(ge=1, le=5)
    landfall_in_h: float = Field(ge=0, le=240)  # from the signal's own time (plan §3)
    track_km: float | None = Field(default=None, ge=0, le=2000)


class AirQuality(_Measure):
    aqi: int = Field(ge=0, le=999)


Measure = Earthquake | Cyclone | AirQuality
MEASURED: dict[str, type[Earthquake] | type[Cyclone] | type[AirQuality]] = {
    "EARTHQUAKE": Earthquake,
    "TROPICAL_CYCLONE": Cyclone,
    "AIR_QUALITY": AirQuality,
}


class HazardError(ValueError):
    """The signal's hazard object is missing or invalid; the reason discards it."""


def measure(category: str, payload: dict[str, Any] | None) -> Measure | None:
    """The typed measure of a measured category (None for other categories)."""
    model = MEASURED.get(category)
    if model is None:
        return None
    raw = (payload or {}).get("hazard")
    if not isinstance(raw, dict):
        raise HazardError(f"no hazard details for {category}")
    try:
        return model.model_validate(raw)
    except ValidationError:
        raise HazardError(f"invalid hazard details for {category}") from None


def earthquake_severity(magnitude: float) -> str:
    if magnitude >= 7.5:
        return "CRITICAL"
    if magnitude >= 6.5:
        return "HIGH"
    if magnitude >= 5.5:
        return "MODERATE"
    return "LOW"


def cyclone_severity(category: int) -> str:
    return "CRITICAL" if category >= 3 else "HIGH" if category == 2 else "MODERATE"


def aqi_severity(aqi: int) -> str | None:
    """None at 200 or less: not an incident (G-5)."""
    if aqi > 400:
        return "CRITICAL"
    if aqi > 300:
        return "HIGH"
    if aqi > 200:
        return "MODERATE"
    return None


def severity(category: str, payload: dict[str, Any] | None) -> str | None:
    """The severity a hazard rule sets, or None when the source's map decides.
    Raises HazardError with the reason to discard the signal."""
    if category == "WILDFIRE":
        return WILDFIRE_SEVERITY
    value = measure(category, payload)
    if isinstance(value, Earthquake):
        return earthquake_severity(value.magnitude)
    if isinstance(value, Cyclone):
        return cyclone_severity(value.cyclone_category)
    if isinstance(value, AirQuality):
        found = aqi_severity(value.aqi)
        if found is None:
            raise HazardError("below threshold")
        return found
    return None


def earthquake_radius_m(magnitude: float) -> int:
    if magnitude >= 7:
        return 400_000
    if magnitude >= 6:
        return 200_000
    if magnitude >= 5:
        return 100_000
    return 50_000


def impact_radius_m(category: str, payload: dict[str, Any] | None = None) -> int:
    if category == "EARTHQUAKE":
        value = measure(category, payload)
        assert isinstance(value, Earthquake)  # normalised signals passed measure() already
        return earthquake_radius_m(value.magnitude)
    return HAZARD_SIZES.get(category) or WEATHER_SIZES.get(category, IMPACT_RADIUS_M)


def fusion_radius_m(category: str, payload: dict[str, Any] | None = None) -> int:
    if category == "EARTHQUAKE" or category in HAZARD_SIZES:
        return impact_radius_m(category, payload)
    return WEATHER_SIZES.get(category, FUSION_RADIUS_M)


def fusion_window_min(category: str) -> int:
    return FUSION_WINDOWS_MIN.get(category, FUSION_WINDOW_MIN)


def landfall_at(
    category: str, payload: dict[str, Any] | None, occurred_at: datetime
) -> datetime | None:
    """A cyclone forecast's landfall: the signal's time plus landfall_in_h (plan §3)."""
    if category != "TROPICAL_CYCLONE":
        return None
    try:
        value = measure(category, payload)
    except HazardError:
        return None
    assert isinstance(value, Cyclone)
    return occurred_at + timedelta(hours=value.landfall_in_h)
