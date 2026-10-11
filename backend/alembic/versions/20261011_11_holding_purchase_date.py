"""Store holding purchase dates for estimated tax basis.

Revision ID: 20261011_11
Revises: 20261011_10
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_11"
down_revision: str | None = "20261011_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            ADD COLUMN purchase_date DATE NOT NULL DEFAULT DATE '2025-01-01'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE holdings DROP COLUMN IF EXISTS purchase_date")
