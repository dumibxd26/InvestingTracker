"""Add transfer fees and stock transfers between accounts.

Revision ID: 20261011_19
Revises: 20261011_18
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_19"
down_revision: str | None = "20261011_18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE cash_transfers
            ADD COLUMN fee_amount NUMERIC(20, 4),
            ADD COLUMN fee_currency currency_code,
            ADD COLUMN fee_side VARCHAR(12),
            ADD CONSTRAINT ck_cash_transfers_fee_positive
                CHECK (fee_amount IS NULL OR fee_amount > 0),
            ADD CONSTRAINT ck_cash_transfers_fee_side
                CHECK (fee_side IS NULL OR fee_side IN ('SOURCE', 'DESTINATION'))
        """
    )
    op.execute(
        """
        CREATE TABLE stock_transfers (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_request_id UUID NOT NULL,
            instrument_id UUID NOT NULL REFERENCES instruments(id),
            source_account_id UUID NOT NULL
                REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            destination_account_id UUID NOT NULL
                REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            quantity NUMERIC(24, 10) NOT NULL,
            average_cost NUMERIC(20, 8) NOT NULL,
            cost_basis NUMERIC(20, 4) NOT NULL,
            fee_amount NUMERIC(20, 4),
            fee_currency currency_code,
            fee_side VARCHAR(12),
            transfer_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_stock_transfers_request UNIQUE (user_id, client_request_id),
            CONSTRAINT ck_stock_transfers_quantity_positive CHECK (quantity > 0),
            CONSTRAINT ck_stock_transfers_distinct_accounts
                CHECK (source_account_id <> destination_account_id),
            CONSTRAINT ck_stock_transfers_fee_positive
                CHECK (fee_amount IS NULL OR fee_amount > 0),
            CONSTRAINT ck_stock_transfers_fee_side
                CHECK (fee_side IS NULL OR fee_side IN ('SOURCE', 'DESTINATION'))
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_stock_transfers_user_date ON stock_transfers (user_id, transfer_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS stock_transfers")
    op.execute(
        """
        ALTER TABLE cash_transfers
            DROP CONSTRAINT IF EXISTS ck_cash_transfers_fee_side,
            DROP CONSTRAINT IF EXISTS ck_cash_transfers_fee_positive,
            DROP COLUMN IF EXISTS fee_side,
            DROP COLUMN IF EXISTS fee_currency,
            DROP COLUMN IF EXISTS fee_amount
        """
    )
