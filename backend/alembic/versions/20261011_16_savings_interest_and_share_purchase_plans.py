"""Add monthly savings interest and discounted share purchase plans.

Revision ID: 20261011_16
Revises: 20261011_15
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_16"
down_revision: str | None = "20261011_15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE account_subaccounts
            ADD COLUMN annual_interest_rate NUMERIC(12, 8),
            ADD COLUMN interest_start_date DATE,
            ADD CONSTRAINT ck_account_subaccounts_interest_rate
                CHECK (annual_interest_rate IS NULL OR
                       (annual_interest_rate >= 0 AND annual_interest_rate <= 1))
        """
    )
    op.execute("ALTER TABLE holdings ADD COLUMN sale_tax_rate NUMERIC(8, 6)")
    op.execute(
        """
        CREATE TABLE stock_purchase_plans (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            funding_subaccount_id UUID NOT NULL
                REFERENCES account_subaccounts(id) ON DELETE CASCADE,
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            holding_id UUID REFERENCES holdings(id) ON DELETE SET NULL,
            name VARCHAR(80) NOT NULL,
            shares NUMERIC(24, 10) NOT NULL,
            purchase_date DATE NOT NULL,
            discount_rate NUMERIC(8, 6) NOT NULL,
            receipt_tax_rate NUMERIC(8, 6) NOT NULL,
            sale_profit_tax_rate NUMERIC(8, 6) NOT NULL,
            reference_price NUMERIC(20, 8),
            status VARCHAR(12) NOT NULL DEFAULT 'scheduled',
            executed_price NUMERIC(20, 8),
            executed_cost NUMERIC(20, 4),
            executed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_stock_purchase_status CHECK (status IN ('scheduled', 'executed')),
            CONSTRAINT ck_stock_purchase_discount
                CHECK (discount_rate >= 0 AND discount_rate < 1)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_stock_purchase_plans_user_date "
        "ON stock_purchase_plans (user_id, purchase_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_purchase_plans")
    op.execute("ALTER TABLE holdings DROP COLUMN IF EXISTS sale_tax_rate")
    op.execute(
        """
        ALTER TABLE account_subaccounts
            DROP CONSTRAINT IF EXISTS ck_account_subaccounts_interest_rate,
            DROP COLUMN IF EXISTS interest_start_date,
            DROP COLUMN IF EXISTS annual_interest_rate
        """
    )
