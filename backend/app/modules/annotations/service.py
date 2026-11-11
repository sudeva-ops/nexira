"""Map annotations (ANN-01..ANN-06; D-52; docs/plan-pilot-map.md §2). Every role of the tenant
reads them; the annotating roles add, edit and withdraw them within their mission scope, checked
through app/core/approvals.py (§115 Q2). An annotation belongs to its incident's mission, else to
the mission nearest it within 300 km, else to none (tenant-wide; plan G-2). Each change is
audited, goes on a linked incident's timeline, and is published as ANNOTATION_UPDATED. Screens get
the author's role, never the person (ANN-04)."""

import json
import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.approvals import ANY_MISSION, roles_of, user_has_role
from app.core.events import Event
from app.core.security import CurrentUser
from app.modules.annotations.models import MapAnnotation
from app.modules.annotations.schemas import (
    SHAPE_OF,
    AnnotationEdit,
    AnnotationIn,
    AnnotationOut,
    AnnotationsOut,
    PointIn,
    PolygonIn,
    Shape,
)
from app.modules.intel.models import IncidentEvent
from app.modules.tenancy.service import ROLES

# §115 Q2, in the order the author's role is named when they hold more than one (plan §2).
ANNOTATORS = ("HQ_CRISIS_DIRECTOR", "SECURITY_OFFICER", "DUTY_OFFICER", "HEAD_OF_MISSION")
NEAREST_MISSION_M = 300_000  # plan G-2
SYMBOL_LABEL = {
    "CHECKPOINT": "Checkpoint",
    "CLOSED_ROAD": "Closed road",
    "RALLY_POINT": "Rally point",
    "HAZARD": "Hazard",
    "NOTE": "Note",
}
KIND_LABEL = {"LINE": "Line", "AREA": "Area"}
VERB = {"ADD": "added", "EDIT": "changed", "WITHDRAW": "withdrawn"}


class AnnotationError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def what(kind: str, symbol: str | None) -> str:
    """ "Checkpoint", "Area": what an annotation is, with no free text (plan G-4)."""
    return SYMBOL_LABEL[symbol] if symbol else KIND_LABEL[kind]


def ewkt(shape: Shape) -> str:
    def pos(p: tuple[float, float]) -> str:
        return f"{p[0]} {p[1]}"

    if isinstance(shape, PointIn):
        body = f"POINT({pos(shape.coordinates)})"
    elif isinstance(shape, PolygonIn):
        body = f"POLYGON(({', '.join(pos(p) for p in shape.coordinates[0])}))"
    else:
        body = f"LINESTRING({', '.join(pos(p) for p in shape.coordinates)})"
    return f"SRID=4326;{body}"


def updated_event(annotation: MapAnnotation) -> Event:
    return Event(
        type="ANNOTATION_UPDATED",
        tenant_id=annotation.tenant_id,
        payload={
            "annotation_id": str(annotation.id),
            "incident_id": str(annotation.incident_id) if annotation.incident_id else None,
        },
        source="annotations",
    )


async def _may(session: AsyncSession, user: CurrentUser, mission_id: uuid.UUID | None) -> bool:
    return await user_has_role(session, user, ANNOTATORS, mission_id)


# --- reading -----------------------------------------------------------------------------------

_ROWS = """
    SELECT a.id, a.kind, a.symbol, ST_AsGeoJSON(a.shape, 6) AS geojson, a.label, a.note,
           a.incident_id, i.reference AS incident_reference, a.mission_id,
           m.code AS mission_code, a.ends_at, a.status, a.reason, a.created_by, a.created_at,
           a.updated_at
      FROM map_annotation a
      LEFT JOIN incident i ON i.id = a.incident_id
      LEFT JOIN mission m ON m.id = a.mission_id
"""
_ACTIVE = text(
    _ROWS
    + """
     WHERE a.status = 'ACTIVE' AND (a.ends_at IS NULL OR a.ends_at > :now)
       AND (CAST(:incident AS uuid) IS NULL OR a.incident_id = :incident)
     ORDER BY a.created_at, a.id
    """
)
_ONE = text(_ROWS + " WHERE a.id = :id")


async def _author_roles(session: AsyncSession, rows: Iterable[Any]) -> dict[uuid.UUID, Any]:
    authors = {r.created_by for r in rows}
    return {a: await roles_of(session, a) for a in authors}


def _role(grants: list[Any], mission_id: uuid.UUID | None) -> str:
    """The author's highest annotating role covering the annotation's mission (ANN-04)."""
    held = {g.code for g in grants if g.mission_id is None or g.mission_id == mission_id}
    for code in ANNOTATORS:
        if code in held:
            return ROLES[code]
    return "A user"  # the role was taken away later; who it was stays in the audit log


async def _outs(session: AsyncSession, user: CurrentUser, rows: list[Any]) -> list[AnnotationOut]:
    authors = await _author_roles(session, rows)
    may: dict[uuid.UUID | None, bool] = {}
    out = []
    for r in rows:
        if r.mission_id not in may:
            may[r.mission_id] = await _may(session, user, r.mission_id)
        out.append(
            AnnotationOut(
                id=r.id,
                kind=r.kind,
                symbol=r.symbol,
                shape=json.loads(r.geojson),
                label=r.label,
                note=r.note,
                incident_id=r.incident_id,
                incident_reference=r.incident_reference,
                mission_code=r.mission_code,
                ends_at=r.ends_at,
                status=r.status,
                reason=r.reason,
                role=_role(authors[r.created_by], r.mission_id),
                created_at=r.created_at,
                updated_at=r.updated_at,
                can_edit=r.status == "ACTIVE" and may[r.mission_id],
            )
        )
    return out


async def listed(
    session: AsyncSession, user: CurrentUser, now: datetime, incident_id: uuid.UUID | None
) -> AnnotationsOut:
    """ANN-02: the ACTIVE annotations whose end has not passed (plan G-7), for every role."""
    rows = list(await session.execute(_ACTIVE, {"now": now, "incident": incident_id}))
    return AnnotationsOut(
        annotations=await _outs(session, user, rows),
        can_add=await user_has_role(session, user, ANNOTATORS, ANY_MISSION),
    )


async def one(session: AsyncSession, user: CurrentUser, annotation_id: uuid.UUID) -> AnnotationOut:
    rows = list(await session.execute(_ONE, {"id": annotation_id}))
    if not rows:
        raise AnnotationError(404, "Annotation not found")
    return (await _outs(session, user, rows))[0]


# --- changing ----------------------------------------------------------------------------------

_INCIDENT = text("SELECT id, mission_id FROM incident WHERE id = :id")
_NEAREST = text(
    """
    SELECT m.id FROM mission m
     WHERE ST_DWithin(m.location, ST_Centroid(ST_GeomFromEWKT(:shape))::geography, :within)
     ORDER BY ST_Distance(m.location, ST_Centroid(ST_GeomFromEWKT(:shape))::geography), m.code
     LIMIT 1
    """
)


async def _mission(
    session: AsyncSession, shape: str, incident_id: uuid.UUID | None
) -> uuid.UUID | None:
    """Plan G-2: the incident's mission; else the nearest within 300 km; else none."""
    if incident_id is not None:
        found = (await session.execute(_INCIDENT, {"id": incident_id})).one_or_none()
        if found is None:
            raise AnnotationError(404, "Incident not found")
        mission: uuid.UUID | None = found.mission_id
        return mission
    nearest: uuid.UUID | None = await session.scalar(
        _NEAREST, {"shape": shape, "within": NEAREST_MISSION_M}
    )
    return nearest


def _iso(at: datetime | None) -> str | None:
    return at.isoformat() if at else None  # the audit details are JSON


def _future(ends_at: datetime | None, now: datetime) -> None:
    if ends_at is not None and ends_at <= now:
        raise AnnotationError(422, "The end time is in the future; withdraw it to end it now")


async def _record(
    session: AsyncSession,
    user: CurrentUser,
    annotation: MapAnnotation,
    action: str,
    details: dict[str, Any],
) -> None:
    """ANN-05 and ANN-06: the audit row and, for a linked incident, its timeline entry."""
    await audit.write(
        session,
        actor_type="USER",
        actor_id=str(user.id),
        action=f"ANNOTATION.{action}",
        entity_type="map_annotation",
        entity_id=str(annotation.id),
        details={"kind": annotation.kind, "symbol": annotation.symbol, **details},
    )
    if annotation.incident_id is None:
        return
    summary = f"Annotation {VERB[action]}: {what(annotation.kind, annotation.symbol)} · "
    summary += annotation.label
    if action == "WITHDRAW":
        summary += f" ({annotation.reason})"
    session.add(
        IncidentEvent(
            tenant_id=annotation.tenant_id,
            incident_id=annotation.incident_id,
            event_type="ANNOTATION",
            summary=summary + ".",
            actor_type="USER",
            actor_id=str(user.id),
            data={
                "annotation_id": str(annotation.id),
                "kind": annotation.kind,
                "symbol": annotation.symbol,
                "action": action,
            },
        )
    )
    await session.flush()


async def add(
    session: AsyncSession, user: CurrentUser, body: AnnotationIn, now: datetime
) -> MapAnnotation:
    _future(body.ends_at, now)
    shape = ewkt(body.shape)
    mission = await _mission(session, shape, body.incident_id)
    if not await _may(session, user, mission):
        raise AnnotationError(403, "Your role may not annotate here")
    annotation = MapAnnotation(
        tenant_id=user.tenant_id,
        mission_id=mission,
        incident_id=body.incident_id,
        kind=body.kind,
        symbol=body.symbol,
        shape=shape,
        label=body.label,
        note=body.note,
        ends_at=body.ends_at,
        created_by=user.id,
    )
    session.add(annotation)
    await session.flush()
    await _record(
        session,
        user,
        annotation,
        "ADD",
        {"label": body.label, "shape": body.shape.model_dump(), "ends_at": _iso(body.ends_at)},
    )
    return annotation


async def _locked(
    session: AsyncSession, user: CurrentUser, annotation_id: uuid.UUID
) -> MapAnnotation:
    annotation = await session.get(
        MapAnnotation, annotation_id, with_for_update=True, populate_existing=True
    )
    if annotation is None:
        raise AnnotationError(404, "Annotation not found")
    if not await _may(session, user, annotation.mission_id):
        raise AnnotationError(403, "Your role may not change this annotation")
    if annotation.status != "ACTIVE":
        raise AnnotationError(409, "The annotation was withdrawn")
    return annotation


async def edit(
    session: AsyncSession,
    user: CurrentUser,
    annotation_id: uuid.UUID,
    body: AnnotationEdit,
    now: datetime,
) -> MapAnnotation:
    annotation = await _locked(session, user, annotation_id)
    changed: dict[str, Any] = {}
    fields = body.model_fields_set
    if "shape" in fields and body.shape is not None:
        if body.shape.type != SHAPE_OF[annotation.kind]:
            raise AnnotationError(422, f"A {annotation.kind} keeps its kind of shape")
        annotation.shape = ewkt(body.shape)
        changed["shape"] = body.shape.model_dump()
    if "label" in fields and body.label is not None:
        annotation.label = changed["label"] = body.label
    if "note" in fields:
        annotation.note = changed["note"] = body.note
    if "ends_at" in fields:
        _future(body.ends_at, now)
        annotation.ends_at = body.ends_at
        changed["ends_at"] = _iso(body.ends_at)
    annotation.updated_by = user.id
    await session.flush()
    await _record(session, user, annotation, "EDIT", changed)
    return annotation


async def withdraw(
    session: AsyncSession, user: CurrentUser, annotation_id: uuid.UUID, reason: str
) -> MapAnnotation:
    annotation = await _locked(session, user, annotation_id)
    annotation.status = "WITHDRAWN"
    annotation.reason = reason
    annotation.withdrawn_by = user.id
    await session.flush()
    await _record(session, user, annotation, "WITHDRAW", {"reason": reason})
    return annotation
