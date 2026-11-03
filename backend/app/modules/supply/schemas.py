import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class SupplierRef(BaseModel):
    id: uuid.UUID
    code: str
    name: str


class MitigationOut(BaseModel):
    """A mitigation (SUP-04). The names of who acted only within the caller's people scope
    (SUP-06); `activated` and `stood_down` say that it happened either way."""

    id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_code: str
    incident_id: uuid.UUID | None
    incident_reference: str | None
    backup: SupplierRef | None
    route_code: str | None
    route_label: str | None
    note: str | None
    activated_at: datetime
    activated_by_name: str | None
    stood_down_at: datetime | None
    stood_down_by_name: str | None
    active: bool


class SupplierOut(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    service: str
    mission_id: uuid.UUID | None  # None: Global
    mission_code: str | None
    city: str | None
    tier: int
    status: str  # reported: NORMAL, WATCH, DELAYED, AT_RISK
    status_detail: str | None
    status_at: datetime
    # Shown (§3): the worst of the reported status and ROUTE_BLOCKED; worked out on read.
    shown: str
    detail: str | None
    impacted: bool
    incident_id: uuid.UUID | None  # the mission's ACTIVE incident, when impacted
    incident_reference: str | None
    backup: SupplierRef | None
    in_bcp: bool
    vetting_valid_until: date
    vetting_current: bool
    performance_score: int | None
    fuel_stock_hours: int | None  # from Fleet's GEN-<mission>, for a fuel supplier (G-7)
    mitigation: MitigationOut | None  # the active one
    source: str


class RouteOut(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    kind: str
    mission_id: uuid.UUID
    mission_code: str
    supplier_id: uuid.UUID | None
    supplier_code: str | None
    alternate_of_code: str | None
    status: str  # reported: OPEN, RESTRICTED, DELAYED, BLOCKED
    shown: str  # the status, or ALTERNATE (§3)
    detail: str | None
    status_at: datetime
    zone_incidents: list[str]  # ACTIVE incidents whose impact zone the path passes through


class SupplierDetailOut(SupplierOut):
    routes: list[RouteOut]
    mitigations: list[MitigationOut]  # newest first, stood down ones included


class ImpactedOut(BaseModel):
    code: str
    name: str
    shown: str
    detail: str | None


class BannerOut(BaseModel):
    """One per ACTIVE incident with impacted suppliers (SUP-03)."""

    incident_id: uuid.UUID
    incident_reference: str
    mission_code: str
    suppliers: list[ImpactedOut]


class SummaryOut(BaseModel):
    suppliers: int
    missions: int
    tier1: int
    impacted: int
    impacted_missions: list[str]
    routes: int
    banners: list[BannerOut]


class MitigationIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
