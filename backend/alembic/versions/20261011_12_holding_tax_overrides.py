"""Allow holding-specific tax horizon overrides.

Revision ID: 20261011_12
Revises: 20261011_11
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_12"
down_revision: str | None = "20261011_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            ADD COLUMN short_term_sale_tax_rate NUMERIC(8, 6),
            ADD COLUMN long_term_sale_tax_rate NUMERIC(8, 6),
            ADD COLUMN long_term_holding_period_days INTEGER
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            DROP COLUMN IF EXISTS long_term_holding_period_days,
            DROP COLUMN IF EXISTS long_term_sale_tax_rate,
            DROP COLUMN IF EXISTS short_term_sale_tax_rate
        """
    )
