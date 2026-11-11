import uuid
from typing import Literal

from pydantic import BaseModel

Group = Literal["STAFF", "DELEGATE", "CITIZEN", "OTHER"]


class PeopleOut(BaseModel):
    """People whose current place is within the radius, by the exposure's groups (plan G-5),
    plus the others (dependants, contractors), so no one is left out silently."""

    staff: int
    delegates: int
    citizens: int
    others: int
    confidence: float | None  # mean location confidence, %
    named: list["NamedPersonOut"]  # nearest first, only within the caller's people scope
    unnamed: int  # those in range whose names this caller may not see (counted above)


class NamedPersonOut(BaseModel):
    id: uuid.UUID
    name: str
    group: Group
    distance_m: int
    confidence: int
    place_label: str | None


class SiteOut(BaseModel):
    id: uuid.UUID
    name: str
    site_type: str
    mission_code: str
    distance_m: int


class VehicleOut(BaseModel):
    id: uuid.UUID
    code: str
    type_label: str
    status: str
    distance_m: int


class TravellersOut(BaseModel):
    people: int  # on a PENDING or APPROVED trip active today; never a restricted trip's (D-33)
    trips: int


class PartnerOut(BaseModel):
    id: uuid.UUID
    name: str
    services: list[str]
    sla_minutes: int


class IncidentOut(BaseModel):
    id: uuid.UUID
    reference: str
    title: str
    severity: str
    category: str
    distance_m: int


class AnnotationOut(BaseModel):
    id: uuid.UUID
    kind: str
    symbol: str | None
    label: str
    distance_m: int  # 0 when the point is inside an area


class NearbyOut(BaseModel):
    """NBY-03: what is within the radius of a point, each kind nearest first."""

    lon: float
    lat: float
    radius_m: int
    country_code: str | None  # the nearest mission's, for the partners (plan G-1)
    mission_code: str | None
    people: PeopleOut
    sites: list[SiteOut]
    vehicles: list[VehicleOut]
    travellers: TravellersOut
    partners: list[PartnerOut]
    incidents: list[IncidentOut]
    annotations: list[AnnotationOut]
