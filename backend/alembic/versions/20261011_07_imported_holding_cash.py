"""Allow imported holdings that do not represent a new cash purchase.

Revision ID: 20261011_07
Revises: 20261011_06
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_07"
down_revision: str | None = "20261011_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE holdings ALTER COLUMN funding_subaccount_id DROP NOT NULL"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM holdings WHERE funding_subaccount_id IS NULL) THEN
                RAISE EXCEPTION
                    'Cannot restore NOT NULL funding_subaccount_id while imported holdings remain';
            END IF;
        END
        $$
        """
    )
    op.execute(
        "ALTER TABLE holdings ALTER COLUMN funding_subaccount_id SET NOT NULL"
    )
