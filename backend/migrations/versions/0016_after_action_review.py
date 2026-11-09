"""After-Action Review (D-47): one review per incident (PC-49) and its lessons and actions
(PC-50).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0016_after_action_review.sql"


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
    # Drops the reviews and their items (D-47).
    _execute_script(
        """
        DROP TABLE aar_item;
        DROP FUNCTION aar_item_guard();
        DROP TABLE after_action_review;
        DROP FUNCTION aar_review_guard();
        """
    )
