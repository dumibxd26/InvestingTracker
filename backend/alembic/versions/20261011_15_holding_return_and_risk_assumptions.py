"""Add editable holding return assumptions and relative risk tiers.

Revision ID: 20261011_15
Revises: 20261011_14
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_15"
down_revision: str | None = "20261011_14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            ADD COLUMN risk_tier VARCHAR(1) NOT NULL DEFAULT 'Y',
            ADD COLUMN expected_annual_return NUMERIC(8, 6) NOT NULL DEFAULT 0.05,
            ADD CONSTRAINT ck_holdings_risk_tier
                CHECK (risk_tier IN ('X', 'Y', 'Z')),
            ADD CONSTRAINT ck_holdings_expected_return_range
                CHECK (expected_annual_return > -1 AND expected_annual_return <= 1)
        """
    )
    op.execute(
        """
        UPDATE holdings AS holding
        SET risk_tier = CASE
            WHEN instrument.instrument_type = 'ETF' THEN 'X'
            ELSE 'Y'
        END
        FROM instruments AS instrument
        WHERE holding.instrument_id = instrument.id
        """
    )
def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE holdings
            DROP CONSTRAINT IF EXISTS ck_holdings_expected_return_range,
            DROP CONSTRAINT IF EXISTS ck_holdings_risk_tier,
            DROP COLUMN IF EXISTS expected_annual_return,
            DROP COLUMN IF EXISTS risk_tier
        """
    )
