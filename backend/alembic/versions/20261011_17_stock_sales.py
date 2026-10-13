"""Add stock sale records.

Revision ID: 20261011_17
Revises: 20261011_16
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_17"
down_revision: str | None = "20261011_16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE stock_sales (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_request_id UUID NOT NULL,
            account_id UUID NOT NULL REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            credited_subaccount_id UUID NOT NULL
                REFERENCES account_subaccounts(id) ON DELETE CASCADE,
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            holding_id UUID REFERENCES holdings(id) ON DELETE SET NULL,
            quantity NUMERIC(24, 10) NOT NULL,
            sell_price NUMERIC(20, 8) NOT NULL,
            currency currency_code NOT NULL,
            proceeds NUMERIC(20, 4) NOT NULL,
            cost_basis NUMERIC(20, 4) NOT NULL,
            realized_pnl NUMERIC(20, 4) NOT NULL,
            sell_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_stock_sales_request UNIQUE (user_id, client_request_id),
            CONSTRAINT ck_stock_sales_quantity_positive CHECK (quantity > 0),
            CONSTRAINT ck_stock_sales_price_positive CHECK (sell_price > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_stock_sales_user_date ON stock_sales (user_id, sell_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_sales")
