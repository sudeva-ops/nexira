import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

KIND = Literal["MARK", "LINE", "AREA"]
SYMBOL = Literal["CHECKPOINT", "CLOSED_ROAD", "RALLY_POINT", "HAZARD", "NOTE"]
MAX_POINTS = 500  # as the table's CHECK (PC-54)

Position = tuple[float, float]  # [lon, lat], GeoJSON order


def _on_earth(points: list[Position]) -> None:
    for lon, lat in points:
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("a position is [lon, lat] on the Earth")


class PointIn(BaseModel):
    type: Literal["Point"]
    coordinates: Position

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _on_earth([self.coordinates])
        return self


class LineIn(BaseModel):
    type: Literal["LineString"]
    coordinates: list[Position] = Field(min_length=2, max_length=MAX_POINTS)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        _on_earth(self.coordinates)
        return self


class PolygonIn(BaseModel):
    """One outer ring, closed here if it is not (ANN-01: an area to avoid, a cordon)."""

    type: Literal["Polygon"]
    coordinates: list[list[Position]] = Field(min_length=1, max_length=1)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        ring = self.coordinates[0]
        if ring and ring[0] != ring[-1]:
            ring = [*ring, ring[0]]
        if len(set(ring)) < 3:
            raise ValueError("an area has at least three corners")
        if len(ring) > MAX_POINTS:
            raise ValueError(f"at most {MAX_POINTS} points")
        _on_earth(ring)
        self.coordinates = [ring]
        return self


Shape = Annotated[PointIn | LineIn | PolygonIn, Field(discriminator="type")]
SHAPE_OF: dict[str, str] = {"MARK": "Point", "LINE": "LineString", "AREA": "Polygon"}


class AnnotationIn(BaseModel):
    kind: KIND
    symbol: SYMBOL | None = None  # a MARK's only
    shape: Shape
    label: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, min_length=1, max_length=280)
    incident_id: uuid.UUID | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _matches(self) -> Self:
        if self.shape.type != SHAPE_OF[self.kind]:
            raise ValueError(f"a {self.kind} is a {SHAPE_OF[self.kind]}")
        if (self.kind == "MARK") != (self.symbol is not None):
            raise ValueError("a mark has a symbol; a line or an area has none")
        return self


class AnnotationEdit(BaseModel):
    """ANN-03: the label, the note, the end time, or a redrawn shape of the same kind (G-3).
    A field left out is unchanged; a note or end time sent as null is cleared."""

    label: str | None = Field(default=None, min_length=1, max_length=80)
    note: str | None = Field(default=None, min_length=1, max_length=280)
    shape: Shape | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _something(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("nothing to change")
        if "label" in self.model_fields_set and self.label is None:
            raise ValueError("an annotation keeps its label")
        if "shape" in self.model_fields_set and self.shape is None:
            raise ValueError("an annotation keeps its shape")
        return self


class WithdrawIn(BaseModel):
    reason: str = Field(min_length=1, max_length=280)


class AnnotationOut(BaseModel):
    """ANN-04: the author's role and the times, never who it was (that is in the audit log)."""

    id: uuid.UUID
    kind: KIND
    symbol: SYMBOL | None
    shape: dict[str, object]  # GeoJSON geometry
    label: str
    note: str | None
    incident_id: uuid.UUID | None
    incident_reference: str | None
    mission_code: str | None
    ends_at: datetime | None
    status: Literal["ACTIVE", "WITHDRAWN"]
    reason: str | None
    role: str  # "Duty Officer"
    created_at: datetime
    updated_at: datetime | None
    can_edit: bool  # the caller may edit or withdraw it


class AnnotationsOut(BaseModel):
    annotations: list[AnnotationOut]
    can_add: bool  # the caller holds a role that may annotate somewhere (§115 Q2)
