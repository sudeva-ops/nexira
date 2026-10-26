"""Journey Management (D-32): trip itinerary (PC-14), trip approval and checklist
(PC-15) and simulated country risk (PC-16).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0003_journey_management.sql"


def _execute_script(sql: str) -> None:
    """Run a multi-statement script on the migration's own connection and transaction
    (as in 0001: asyncpg runs a parameterless execute() as a simple query)."""
    bind = op.get_bind()
    bind.exec_driver_sql("SELECT 1")  # makes sure the driver transaction has begun
    driver: Any = bind.connection.dbapi_connection
    driver.run_async(lambda conn: conn.execute(sql))


def upgrade() -> None:
    _execute_script(UPGRADE_SQL.read_text(encoding="utf-8"))


def downgrade() -> None:
    # Fails on purpose if a trip is DRAFT or CANCELLED: those states do not exist in 0002.
    _execute_script(
        """
        GRANT DELETE ON trip TO nexira_app;
        DROP TRIGGER trip_segment_guard ON trip_segment;
        DROP TRIGGER trip_traveller_guard ON trip_traveller;
        DROP FUNCTION trip_child_guard();
        DROP TRIGGER trip_guard ON trip;
        DROP FUNCTION trip_guard();
        ALTER TABLE trip DROP CONSTRAINT trip_submitted_check;
        ALTER TABLE trip DROP CONSTRAINT trip_approval_only_check;
        ALTER TABLE trip DROP CONSTRAINT trip_approver_check;
        ALTER TABLE trip DROP CONSTRAINT trip_approved_check;
        ALTER TABLE trip
          DROP COLUMN checklist, DROP COLUMN rejection_reason, DROP COLUMN approved_risk_level,
          DROP COLUMN approved_at, DROP COLUMN approved_by, DROP COLUMN submitted_at,
          DROP COLUMN requested_by, DROP COLUMN mission_id;
        ALTER TABLE trip ALTER COLUMN approval_status SET DEFAULT 'PENDING';
        ALTER TABLE trip DROP CONSTRAINT trip_approval_status_check;
        ALTER TABLE trip ADD CONSTRAINT trip_approval_status_check
          CHECK (approval_status IN ('PENDING','APPROVED','REJECTED'));
        DROP TABLE trip_segment;
        DROP TABLE country_risk;
        """
    )
