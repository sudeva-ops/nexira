"""Site Twin camera coverage (D-51): four seeded cameras re-aimed along their walls. Data only.

Runs as nexira_owner (D-01). No schema, grant or RLS change.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-10
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0019_camera_aim.sql"


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
    # Puts back the aims of 0018.
    _execute_script(
        UPGRADE_SQL.read_text(encoding="utf-8")
        .replace("('CAM-11', 130, 110, 190)", "('CAM-11', 125, 100, 190)")
        .replace("('CAM-12', 225, 110, 205)", "('CAM-12', 235, 100, 200)")
        .replace("('CAM-13', 130, 110, 210)", "('CAM-13', 125, 100, 210)")
        .replace("('CAM-16', 130, 110, 200)", "('CAM-16', 125, 100, 200)")
    )
