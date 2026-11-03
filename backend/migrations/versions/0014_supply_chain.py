"""Supply Chain & Third-Party Risk (D-44): suppliers (PC-43), logistics routes (PC-44) and
mitigations (PC-45).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0014_supply_chain.sql"


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
    # Drops the supply data: the register and routes are illustrative and reseeded (D-44).
    _execute_script(
        """
        DROP TABLE supply_mitigation;
        DROP FUNCTION supply_mitigation_guard();
        DROP TABLE logistics_route;
        DROP FUNCTION supply_route_guard();
        DROP TABLE supplier;
        DROP FUNCTION supply_supplier_guard();
        """
    )
