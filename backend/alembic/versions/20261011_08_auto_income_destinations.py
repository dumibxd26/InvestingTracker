"""Add destination wallets and automatic posting to cash-flow schedules.

Revision ID: 20261011_08
Revises: 20261011_07
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_08"
down_revision: str | None = "20261011_07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cash_flow_schedules
            ADD COLUMN account_id UUID
                REFERENCES accounts_brokers(id) ON DELETE SET NULL,
            ADD COLUMN subaccount_id UUID
                REFERENCES account_subaccounts(id) ON DELETE SET NULL,
            ADD COLUMN auto_post BOOLEAN NOT NULL DEFAULT FALSE,
            ADD CONSTRAINT ck_cash_flow_schedules_auto_post_destination
                CHECK (
                    NOT auto_post
                    OR (
                        kind IN ('salary', 'bonus')
                        AND account_id IS NOT NULL
                        AND subaccount_id IS NOT NULL
                    )
                )
        """
    )
    op.execute(
        """
        ALTER TABLE cash_flows
            ADD COLUMN schedule_id UUID
                REFERENCES cash_flow_schedules(id) ON DELETE SET NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE cash_flow_schedules
            DROP CONSTRAINT IF EXISTS ck_cash_flow_schedules_auto_post_destination,
            DROP COLUMN IF EXISTS auto_post,
            DROP COLUMN IF EXISTS subaccount_id,
            DROP COLUMN IF EXISTS account_id
        """
    )
    op.execute("ALTER TABLE cash_flows DROP COLUMN IF EXISTS schedule_id")
