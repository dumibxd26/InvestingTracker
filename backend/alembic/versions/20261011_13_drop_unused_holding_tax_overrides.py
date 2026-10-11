"""Drop unused per-holding tax overrides.

Revision ID: 20261011_13
Revises: 20261011_12
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_13"
down_revision: str | None = "20261011_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM holdings
                WHERE short_term_sale_tax_rate IS NOT NULL
                    OR long_term_sale_tax_rate IS NOT NULL
                    OR long_term_holding_period_days IS NOT NULL
            ) THEN
                RAISE EXCEPTION
                    'Cannot drop holding-specific tax assumptions while values are configured';
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE holdings
            DROP COLUMN short_term_sale_tax_rate,
            DROP COLUMN long_term_sale_tax_rate,
            DROP COLUMN long_term_holding_period_days
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            ADD COLUMN short_term_sale_tax_rate NUMERIC(8, 6),
            ADD COLUMN long_term_sale_tax_rate NUMERIC(8, 6),
            ADD COLUMN long_term_holding_period_days INTEGER
        """
    )
