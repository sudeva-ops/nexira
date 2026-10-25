"""Only state conflicts become 409; faults stay 5xx (plan G-08, review of Prompt 9)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import create_engine, tenant_session
from app.core.errors import is_rule_violation
from app.tests.conftest import DbUrls


class DriverError(Exception):
    def __init__(self, sqlstate: str | None, message: str = "") -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


@pytest.mark.parametrize(
    ("sqlstate", "message", "conflict"),
    [
        ("23505", "duplicate key", True),  # e.g. a second live playbook run
        ("23514", "check constraint", True),
        ("P0001", "<class 'RaiseError'>: agents are paused (kill switch)", True),
        ("P0001", "<class 'RaiseError'>: proposal_approval: step 1 already decided", True),
        ("P0001", "<class 'RaiseError'>: agent_proposal: effective_level ... immutable", True),
        ("P0001", "<class 'RaiseError'>: notification_campaign: the author cannot approve", True),
        # Faults, not conflicts:
        ("P0001", "<class 'RaiseError'>: next_reference: app.tenant_id is not set", False),
        ("P0001", "<class 'RaiseError'>: audit_log is append-only", False),
        ("23503", "foreign key violation", False),
        ("23502", "not null violation", False),
        ("08006", "connection failure", False),
        (None, "", False),
    ],
)
def test_rule_violations(sqlstate: str | None, message: str, conflict: bool) -> None:
    error = DBAPIError("statement", {}, DriverError(sqlstate, message))
    assert is_rule_violation(error) is conflict


async def test_a_real_trigger_fault_is_not_a_conflict(db: DbUrls) -> None:
    """The message format the prefix match relies on, from a real trigger: with no
    tenant set, next_reference() raises P0001, which is a fault (D-02), not a 409."""
    engine = create_engine(db.api)
    try:
        async with tenant_session(None, engine) as session:
            with pytest.raises(DBAPIError) as info:
                await session.execute(text("SELECT next_reference('NTF', false)"))
    finally:
        await engine.dispose()
    assert getattr(info.value.orig, "sqlstate", None) == "P0001"
    assert "next_reference: app.tenant_id is not set" in str(info.value.orig)
    assert is_rule_violation(info.value) is False
    refusal = DBAPIError(
        "s",
        {},
        DriverError(
            "P0001",
            str(info.value.orig).replace(
                "next_reference: app.tenant_id is not set", "agents are paused (kill switch)"
            ),
        ),
    )
    assert is_rule_violation(refusal) is True
