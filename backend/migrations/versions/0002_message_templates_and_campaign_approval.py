"""Message templates (PC-07) and campaign approval (PC-08, hardened by PC-10), for
Mass Notification (D-31), PC-11 (approval binds the content) and PC-12 (status only
moves forward; check-in answers and deliveries are evidence).

Runs as nexira_owner (D-01). nexira_backup reads the new table through the default
privileges in infra/postgres/backup-grants.sql; nexira_app gets explicit grants here.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = Path(__file__).parent.parent / "sql" / "0002_message_templates_and_campaign_approval.sql"


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
    # Fails on purpose if a campaign is PENDING_APPROVAL: send or cancel it first.
    _execute_script(
        """
        GRANT DELETE ON notification_campaign, notification_delivery, checkin_response
          TO nexira_app;
        GRANT UPDATE ON checkin_response TO nexira_app;
        DROP TRIGGER notification_delivery_guard ON notification_delivery;
        DROP FUNCTION notification_delivery_guard();
        DROP TRIGGER notification_campaign_approval_guard ON notification_campaign;
        DROP FUNCTION notification_campaign_approval_guard();
        ALTER TABLE notification_campaign DROP CONSTRAINT notification_campaign_escalate_check;
        ALTER TABLE notification_campaign DROP CONSTRAINT notification_campaign_approved_check;
        ALTER TABLE notification_campaign DROP CONSTRAINT notification_campaign_submitted_check;
        ALTER TABLE notification_campaign
          DROP COLUMN rejection_reason, DROP COLUMN approved_at, DROP COLUMN approved_by,
          DROP COLUMN submitted_by, DROP COLUMN template_id;
        ALTER TABLE notification_campaign DROP CONSTRAINT notification_campaign_status_check;
        ALTER TABLE notification_campaign ADD CONSTRAINT notification_campaign_status_check
          CHECK (status IN ('DRAFT','SENDING','SENT','CANCELLED'));
        DROP TABLE message_template;
        """
    )
