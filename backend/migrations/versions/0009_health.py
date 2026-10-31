"""Health Intelligence (D-39): advisories (PC-26, with topic_code by plan-pilot-hl G-1),
medical facilities (PC-27), entry requirements (PC-28) and readiness counts (PC-29).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0009_health.sql"


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
    # Drops the health data: simulated and illustrative, reseeded (D-39). Rows that
    # next_reference('HA') wrote at runtime stay in reference_counter, as other modules' do.
    _execute_script(
        """
        DROP TABLE mission_health_readiness;
        DROP FUNCTION mission_health_readiness_guard();
        DROP TABLE country_health_requirement;
        DROP TABLE medical_facility;
        DROP FUNCTION medical_facility_guard();
        DROP TABLE health_advisory;
        DROP FUNCTION health_advisory_guard();
        """
    )
