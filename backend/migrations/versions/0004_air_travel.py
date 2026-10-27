"""Air Travel Tracking (D-33): segment flight fields and restricted trips (PC-17),
simulated airports (PC-18), and tracked flights with their events (PC-19).

Runs as nexira_owner (D-01). nexira_backup reads the new tables through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0004_air_travel.sql"


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
    # Drops every flight, airport and segment flight field: simulated data only (D-33).
    _execute_script(
        """
        DROP TABLE flight_event;
        DROP TABLE flight;
        DROP FUNCTION flight_event_guard();
        DROP FUNCTION flight_guard();
        DROP TRIGGER trip_restricted_guard ON trip;
        DROP FUNCTION trip_restricted_guard();
        ALTER TABLE trip DROP COLUMN restricted;
        ALTER TABLE trip_segment
          DROP CONSTRAINT trip_segment_flight_check,
          DROP CONSTRAINT trip_segment_to_airport_fk,
          DROP CONSTRAINT trip_segment_from_airport_fk,
          DROP COLUMN to_airport, DROP COLUMN from_airport, DROP COLUMN flight_number;
        DROP TABLE airport;
        """
    )
