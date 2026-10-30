"""HTTP status codes for refusals that come from the rules (plan G-08).

- approvals.ApprovalDeniedError carries its own 403 or 409.
- A database rule that refuses a request because of the current state is a
  409, never a 500: a unique or check violation, or one of the schema's
  refusal triggers (listed below). The rules are checked in Python first; this
  is the backstop.
- Everything else stays a 5xx and is logged as an error, because it means a
  bug or tampering, not a conflict: a missing tenant setting (next_reference),
  an attempt to change audit_log, a foreign-key or NOT NULL violation, a lost
  connection.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core.approvals import ApprovalDeniedError

log = logging.getLogger(__name__)

CONFLICT_SQLSTATES = ("23505", "23514")  # unique violation, check violation
# Messages of the schema's RAISE EXCEPTION refusals (docs/schema/nexira_schema.sql)
# that mean "not allowed in the current state".
REFUSAL_PREFIXES = (
    "agents are paused",  # D-17 kill switch
    "agent ",  # agent is disabled
    "agent_proposal:",  # frozen proposal fields (D-12)
    "proposal_approval:",  # approval order and decided-once (D-16)
    "notification_campaign:",  # approval, frozen content, forward-only status (D-31)
    "notification_delivery:",  # a delivery keeps its campaign, person and channel
    "trip:",  # approval, frozen trip and itinerary, forward-only status (D-32)
    "flight:",  # only approved, unrestricted trips; status table; append-only events (D-33)
    "weather:",  # a row's mission is in its own tenant and never changes (D-35)
)


def is_rule_violation(error: DBAPIError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or ""
    if sqlstate in CONFLICT_SQLSTATES:
        return True
    if sqlstate == "P0001":
        message = str(error.orig)
        return any(message.startswith(p) or f": {p}" in message for p in REFUSAL_PREFIXES)
    return False


def install(app: FastAPI) -> None:
    @app.exception_handler(ApprovalDeniedError)
    async def approval_denied(_request: Request, exc: ApprovalDeniedError) -> JSONResponse:
        return JSONResponse({"detail": exc.verdict.reason}, status_code=exc.verdict.status_code)

    @app.exception_handler(DBAPIError)
    async def database_rule(request: Request, exc: DBAPIError) -> JSONResponse:
        if not is_rule_violation(exc):
            log.error("database error on %s %s: %s", request.method, request.url.path, exc.orig)
            raise exc
        log.info("database rule refused a request: %s", exc.orig)
        return JSONResponse(
            {"detail": "The request conflicts with the current state"},
            status_code=status.HTTP_409_CONFLICT,
        )
