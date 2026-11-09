"""Exercise & Training (D-48): exercises on the scenario engine (PC-51) and their frozen scores
(PC-52).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0017_exercises.sql"


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
    # Drops the exercises, their scores and the guard on their runs (D-48).
    _execute_script(
        """
        DROP TRIGGER exercise_run_guard ON scenario_run;
        DROP FUNCTION exercise_run_guard();
        DROP TABLE exercise_score;
        DROP FUNCTION exercise_score_guard();
        DROP TABLE exercise;
        DROP FUNCTION exercise_guard();
        DROP FUNCTION exercise_scored_check();
        DROP FUNCTION exercise_no_truncate_guard();
        """
    )
