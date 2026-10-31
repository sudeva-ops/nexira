"""Natural Hazards & Climate (D-38): armed playbook runs (PC-24) and climate risk (PC-25).

Runs as nexira_owner (D-01). nexira_backup reads the new table through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0008_hazards.sql"


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
    # Fails on purpose if a run is SCHEDULED or DISARMED: those states do not exist in 0007
    # (plan-pilot-hz.md §11). Drops the climate scores: simulated data, reseeded (D-38).
    _execute_script(
        """
        DROP TABLE mission_climate_risk;
        DROP FUNCTION mission_climate_risk_guard();
        DROP TRIGGER playbook_run_guard ON playbook_run;
        DROP FUNCTION playbook_run_guard();
        DROP INDEX playbook_run_live_uq;
        CREATE UNIQUE INDEX playbook_run_live_uq ON playbook_run (playbook_id, incident_id)
          WHERE status IN ('RUNNING','AWAITING_APPROVAL');
        ALTER TABLE playbook_run DROP CONSTRAINT playbook_run_status_check;
        ALTER TABLE playbook_run ADD CONSTRAINT playbook_run_status_check CHECK (status IN (
          'RUNNING','AWAITING_APPROVAL','COMPLETED','CANCELLED','FAILED'));
        ALTER TABLE playbook_run DROP COLUMN scheduled_for;
        """
    )
