"""Support named equity awards, custom tranches, and sale-tax scenarios.

Revision ID: 20261011_09
Revises: 20261011_08
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_09"
down_revision: str | None = "20261011_08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE vesting_grants
            ADD COLUMN grant_label VARCHAR(80),
            ADD COLUMN short_term_sale_tax_rate NUMERIC(8, 6)
                NOT NULL DEFAULT 0.06,
            ADD COLUMN long_term_sale_tax_rate NUMERIC(8, 6)
                NOT NULL DEFAULT 0.03,
            ADD COLUMN long_term_holding_period_days INTEGER
                NOT NULL DEFAULT 365
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE vesting_grants
            DROP COLUMN IF EXISTS long_term_holding_period_days,
            DROP COLUMN IF EXISTS long_term_sale_tax_rate,
            DROP COLUMN IF EXISTS short_term_sale_tax_rate,
            DROP COLUMN IF EXISTS grant_label
        """
    )
