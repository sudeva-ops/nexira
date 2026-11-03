"""Predictive Risk (D-46): the daily risk index (PC-46) and the events calendar (PC-47). PC-48
is an agent row only (plan-pilot-prd G-1, option B), seeded, with no table.

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-03
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0015_predictive.sql"


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
    # Drops the index history and the calendar: illustrative and reseeded (D-46).
    _execute_script(
        """
        DROP TABLE mission_event;
        DROP FUNCTION predictive_mission_event_guard();
        DROP TABLE risk_index;
        DROP FUNCTION predictive_risk_index_guard();
        """
    )
