import uuid
from datetime import date, datetime

from pydantic import BaseModel


class SiteSummaryOut(BaseModel):
    """A site with a floor plan, for the picker (TWN-06)."""

    id: uuid.UUID
    name: str
    site_type: str
    mission_id: uuid.UUID
    mission_code: str
    city: str


class ZoneOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    kind: str
    x: int
    y: int
    w: int
    h: int
    capacity: int | None
    count: int  # occupants in the zone now


class OccupantOut(BaseModel):
    """One dot on the plan (TWN-02). A staff name only within the caller's people scope;
    guards and visitors are labels, never names."""

    id: uuid.UUID
    kind: str  # STAFF, GUARD, VISITOR
    zone_code: str
    name: str | None  # STAFF within scope only
    label: str | None  # GUARD, VISITOR
    since: datetime


class SensorOut(BaseModel):
    code: str
    kind: str
    label: str
    zone_code: str | None
    status: str  # OK, DEGRADED, FAULT, OFFLINE
    detail: str | None
    status_at: datetime
    online: bool  # OK or DEGRADED (plan G-2)


class SystemOut(BaseModel):
    """The generator or satellite comms, from Fleet & Assets (TWN-03, §68 Q5)."""

    code: str
    label: str
    state: str
    fuel_pct: int | None


class RouteOut(BaseModel):
    code: str
    label: str
    path: list[list[int]]
    exit_zone_code: str
    evacuation_reference: str


class ShelterOut(BaseModel):
    incident_id: uuid.UUID
    incident_reference: str


class ReadinessItemOut(BaseModel):
    id: uuid.UUID | None  # None for the derived item
    label: str
    done: bool
    done_by_name: str | None
    done_at: datetime | None
    derived: bool = False  # "All access points monitored", from the sensors
    detail: str | None = None


class ReadinessOut(BaseModel):
    score: int | None  # site.readiness_score (plan G-1)
    last_drill_on: date | None
    items: list[ReadinessItemOut]


class CountsOut(BaseModel):
    on_site: int
    staff: int
    guards: int
    visitors: int
    safe_room: int
    safe_room_capacity: int | None
    sensors_online: int
    sensors: int
    faults: int


class TwinOut(BaseModel):
    site: SiteSummaryOut
    zones: list[ZoneOut]
    occupants: list[OccupantOut]
    sensors: list[SensorOut]
    systems: list[SystemOut]
    counts: CountsOut
    shelter: ShelterOut | None  # worked out on read (TWN-04)
    route: RouteOut | None  # while the mission has an ACTIVE evacuation
    readiness: ReadinessOut
    source: str = "Access control, CCTV and building systems (simulated)"
    simulated: bool = True  # D-19
