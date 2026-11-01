"""VIP & Delegation Protection (D-42): visits (PC-35), segments (PC-36), checklist items
(PC-37) and two-person segment changes (PC-38).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0012_vip.sql"


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
    # Drops the visit data: visits are illustrative and reseeded (D-42). Rows that
    # next_reference('VV') wrote at runtime stay in reference_counter, as other modules' do.
    _execute_script(
        """
        DROP TABLE vip_checklist_item;
        DROP FUNCTION vip_checklist_item_guard();
        DROP TABLE vip_segment_change;
        DROP FUNCTION vip_segment_change_guard();
        DROP TABLE vip_segment;
        DROP FUNCTION vip_segment_guard();
        DROP TABLE vip_visit;
        DROP FUNCTION vip_visit_guard();
        """
    )
