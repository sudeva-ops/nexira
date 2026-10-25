"""HTTP status codes for refusals that come from the rules (plan G-08).

- approvals.ApprovalDeniedError carries its own 403 or 409.
- A database rule that still fires (a unique index, a check, or a trigger that
  raises) is a conflict with the current state: 409, never 500. The rules are
  checked in Python first; this is the backstop. Other database errors (lost
  connection, timeouts) are left alone and stay 5xx.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from app.core.approvals import ApprovalDeniedError

log = logging.getLogger(__name__)

# SQLSTATE classes and codes that mean "the data rules refused this".
CONFLICT_CLASSES = ("23",)  # integrity constraint violation
CONFLICT_CODES = ("P0001",)  # RAISE EXCEPTION in a trigger


def is_rule_violation(error: DBAPIError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or ""
    return sqlstate.startswith(CONFLICT_CLASSES) or sqlstate in CONFLICT_CODES


def install(app: FastAPI) -> None:
    @app.exception_handler(ApprovalDeniedError)
    async def approval_denied(_request: Request, exc: ApprovalDeniedError) -> JSONResponse:
        return JSONResponse({"detail": exc.verdict.reason}, status_code=exc.verdict.status_code)

    @app.exception_handler(DBAPIError)
    async def database_rule(_request: Request, exc: DBAPIError) -> JSONResponse:
        if not is_rule_violation(exc):
            raise exc
        log.info("database rule refused a request: %s", exc.orig)
        return JSONResponse(
            {"detail": "The request conflicts with the current state"},
            status_code=status.HTTP_409_CONFLICT,
        )
