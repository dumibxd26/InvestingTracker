"""Move editable security tax domicile to the user-owned holding.

Revision ID: 20261014_22
Revises: 20261014_21
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_22"
down_revision: str | None = "20261014_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            ADD COLUMN tax_domicile_country_code VARCHAR(2),
            ADD CONSTRAINT ck_holdings_tax_domicile_country_code
                CHECK (
                    tax_domicile_country_code IS NULL
                    OR tax_domicile_country_code ~ '^[A-Z]{2}$'
                )
        """
    )
    op.execute(
        """
        UPDATE holdings
        SET tax_domicile_country_code = instruments.tax_domicile_country_code
        FROM instruments
        WHERE holdings.instrument_id = instruments.id
          AND holdings.tax_domicile_country_code IS NULL
          AND instruments.tax_domicile_country_code IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            DROP CONSTRAINT ck_holdings_tax_domicile_country_code,
            DROP COLUMN tax_domicile_country_code
        """
    )
