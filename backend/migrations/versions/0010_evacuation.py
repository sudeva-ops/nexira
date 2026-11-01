"""Evacuation Management (D-40): plans (PC-30), evacuations (PC-31, with requested_role by
plan-pilot-ev G-1) and manifests (PC-32).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0010_evacuation.sql"


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
    # Drops the evacuation data: plans are illustrative and reseeded, and every evacuation
    # was simulated (D-40). Rows that next_reference('EVN') wrote at runtime stay in
    # reference_counter, as other modules' do.
    _execute_script(
        """
        DROP TABLE evacuation_manifest;
        DROP FUNCTION evacuation_manifest_guard();
        DROP TABLE evacuation;
        DROP FUNCTION evacuation_guard();
        DROP TABLE evacuation_plan;
        DROP FUNCTION evacuation_plan_guard();
        """
    )
