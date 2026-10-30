"""Partner adapters (AS-04; D-36, docs/plan-pilot-ast.md §3). Changes need human sign-off
(D-29): this is the boundary to an external system, like the channel adapters.

The pilot has no real partners: every request is answered by SimulatedPartnerAdapter,
which makes no network call and contacts nobody (AGENTS.md). adapter_for() is the only way
to get an adapter, and it refuses any other configuration, so a real integration cannot be
switched on by a setting.

Contract for any future adapter: respond() says what the partner does next with a request
in its current state, or None. It is called repeatedly by the worker, so it must be safe
to call again: the same request in the same state at the same moment gives the same answer.
Accepting, declining and going en route are the partner's; completing and cancelling are
ours (a person, through the API).
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

Move = Literal["ACCEPTED", "DECLINED", "EN_ROUTE"]


@dataclass(frozen=True)
class Pending:
    """What a partner is told about a request (AS-08) and its state."""

    id: uuid.UUID
    status: str  # REQUESTED or ACCEPTED: the states in which a partner acts
    sla_minutes: int
    has_incident: bool
    requested_at: datetime
    accepted_at: datetime | None


@dataclass(frozen=True)
class Response:
    status: Move
    eta: datetime | None = None


class PartnerAdapter(Protocol):
    name: str

    def respond(self, request: Pending, now: datetime) -> Response | None: ...


def _fraction(request_id: uuid.UUID, salt: str) -> float:
    """A stable number in [0, 1) for a request (hash() is salted per process)."""
    digest = hashlib.sha256(f"{salt}:{request_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") / 2**32


class SimulatedPartnerAdapter:
    """Pretends to be every partner (§33 Q4, plan G-2). Deterministic from the request id:
    accepts 5-15 s after the request with an ETA from the SLA, goes en route 10 s after
    accepting, and declines about 1 in 10 requests that are not about an incident (so a
    demo request, which always names its incident, is never declined)."""

    name = "simulated"
    EN_ROUTE_AFTER = timedelta(seconds=10)
    DECLINE_SHARE = 0.1

    def accept_after(self, request_id: uuid.UUID) -> timedelta:
        return timedelta(seconds=5 + 10 * _fraction(request_id, "accept"))

    def declines(self, request: Pending) -> bool:
        return not request.has_incident and _fraction(request.id, "decline") < self.DECLINE_SHARE

    def respond(self, request: Pending, now: datetime) -> Response | None:
        if request.status == "REQUESTED":
            if now - request.requested_at < self.accept_after(request.id):
                return None
            if self.declines(request):
                return Response("DECLINED")
            return Response("ACCEPTED", eta=now + timedelta(minutes=request.sla_minutes))
        if (
            request.status == "ACCEPTED"
            and request.accepted_at is not None
            and now - request.accepted_at >= self.EN_ROUTE_AFTER
        ):
            return Response("EN_ROUTE")
        return None


class UnsupportedPartnerAdapterError(ValueError):
    pass


def adapter_for(configured: str = "simulated") -> PartnerAdapter:
    """The only adapter in the pilot (D-36). Anything else is refused, not ignored."""
    if configured != SimulatedPartnerAdapter.name:
        raise UnsupportedPartnerAdapterError(
            f"partner adapter {configured!r} is not available: partners are simulated (D-36)"
        )
    return SimulatedPartnerAdapter()
