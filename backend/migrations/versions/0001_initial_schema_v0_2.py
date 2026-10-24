"""Initial schema: docs/schema/nexira_schema.sql v0.2, unchanged.

Runs as nexira_owner (D-01). The SQL file is a verbatim copy of the docs file;
app/tests/test_migrations.py fails if the two ever differ.

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_SQL = Path(__file__).parent.parent / "sql" / "0001_nexira_schema_v0_2.sql"

VIEWS = ("v_incident_people_in_zone", "v_checkin_latest")

# Reverse dependency order; CASCADE covers the remaining foreign keys.
TABLES = (
    "scenario_run", "scenario_event", "scenario",
    "audit_log", "reference_counter",
    "proposal_approval", "playbook_run_step", "playbook_run", "agent_proposal",
    "action_policy", "agent",
    "checkin_response", "notification_delivery", "notification_campaign",
    "playbook_step", "playbook",
    "incident_event", "incident_exposure", "incident_signal", "incident", "raw_signal",
    "intel_source", "trip_traveller", "trip",
    "person_location_current", "location_observation", "person", "site", "user_role",
    "mission", "role", "app_user", "tenant",
)  # fmt: skip

FUNCTIONS = (
    "resolve_tenant_by_issuer(text)",
    "audit_verify_chain()",
    "audit_log_block_mutation()",
    "audit_log_chain()",
    "next_reference(text, boolean)",
    "agent_proposal_create_approvals()",
    "proposal_approval_in_order()",
    "agent_proposal_freeze()",
    "agent_proposal_set_level()",
    "severity_rank(text)",
    "current_tenant_id()",
    "set_updated_at()",
)


def _execute_script(sql: str) -> None:
    """Run a multi-statement script on the migration's own connection and transaction.

    asyncpg sends a parameterless execute() as a simple query, which accepts many
    statements, $$-quoted bodies and DO blocks.
    """
    bind = op.get_bind()
    bind.exec_driver_sql("SELECT 1")  # makes sure the driver transaction has begun
    driver: Any = bind.connection.dbapi_connection
    driver.run_async(lambda conn: conn.execute(sql))


def upgrade() -> None:
    _execute_script(SCHEMA_SQL.read_text(encoding="utf-8"))
    # Alembic's own table existed when the schema granted ON ALL TABLES to nexira_app.
    # The API must not be able to change migration state.
    op.execute("REVOKE ALL ON alembic_version FROM nexira_app")


def downgrade() -> None:
    # Extensions and roles belong to init.sql (superuser) and are left alone (plan G-27).
    for view in VIEWS:
        op.execute(f"DROP VIEW IF EXISTS {view}")
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for function in FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
