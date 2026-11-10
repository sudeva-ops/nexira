"""Site Twin camera coverage (D-51): where each camera is mounted and points (PC-53).

Runs as nexira_owner (D-01). No grant or RLS change.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-10
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0018_camera_mounts.sql"


def _execute_script(sql: str) -> None:
    """Run a multi-statement script on the migration's own connection and transaction
    (as in 0001: asyncpg runs a parameterless execute() as a simple query)."""
    bind = op.get_bind()
    bind.exec_driver_sql("SELECT 1")  # makes sure the driver transaction has begun
    driver: Any = bind.connection.dbapi_connection
    driver.run_async(lambda conn: conn.execute(sql))


def upgrade() -> None:
    _execute_script(UPGRADE_SQL.read_text(encoding="utf-8"))


def _guard_0013() -> str:
    """The sensor guard as 0013 wrote it, character for character."""
    sql = (UPGRADE_SQL.parent / "0013_site_twin.sql").read_text(encoding="utf-8")
    start = sql.index("CREATE FUNCTION site_sensor_guard()")
    end = sql.index("CREATE TRIGGER site_sensor_guard")
    return sql[start:end].replace("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION", 1)


def downgrade() -> None:
    # Puts back the guard of 0013, then drops the mounts (D-51).
    _execute_script(
        _guard_0013()
        + """
        ALTER TABLE site_sensor DROP CONSTRAINT site_sensor_mount_check;
        ALTER TABLE site_sensor
          DROP COLUMN mount_x,
          DROP COLUMN mount_y,
          DROP COLUMN heading_deg,
          DROP COLUMN fov_deg,
          DROP COLUMN range_u;
        """
    )
