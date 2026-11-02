"""Site Twin (D-43): floor plan zones (PC-39), evacuation routes (PC-40), presence (PC-41),
and sensors and readiness items (PC-42; plan-pilot-twn G-1: no site_readiness table).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-02
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0013_site_twin.sql"


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
    # Drops the site twin data: plans, presence and sensors are illustrative and reseeded (D-43).
    _execute_script(
        """
        DROP TABLE site_readiness_item;
        DROP FUNCTION site_readiness_item_guard();
        DROP TABLE site_sensor;
        DROP FUNCTION site_sensor_guard();
        DROP TABLE site_presence;
        DROP FUNCTION site_presence_guard();
        DROP TABLE site_route;
        DROP FUNCTION site_route_guard();
        DROP TABLE site_zone;
        DROP FUNCTION site_zone_guard();
        """
    )
