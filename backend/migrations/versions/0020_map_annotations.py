"""Map annotations (D-52): marks, lines and areas on the world map (PC-54).

Runs as nexira_owner (D-01). nexira_backup reads the new table through the default privileges
in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-11
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0020_map_annotations.sql"


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
    # Drops the annotations and their guards (D-52).
    _execute_script(
        """
        DROP TABLE map_annotation;
        DROP FUNCTION map_annotation_guard();
        DROP FUNCTION map_annotation_no_truncate_guard();
        """
    )
