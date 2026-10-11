"""Record acquisition spend in each holding's funding currency.

Revision ID: 20261011_06
Revises: 20261011_05
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_06"
down_revision: str | None = "20261011_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE holdings "
        "ADD COLUMN IF NOT EXISTS funding_cost NUMERIC(20, 4) NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        UPDATE holdings AS holding
        SET funding_cost = ROUND(
            (holding.quantity * holding.average_cost)::numeric,
            4
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE holdings DROP COLUMN IF EXISTS funding_cost")
