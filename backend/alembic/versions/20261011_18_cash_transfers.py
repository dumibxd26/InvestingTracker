"""Add cash transfers between wallets.

Revision ID: 20261011_18
Revises: 20261011_17
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_18"
down_revision: str | None = "20261011_17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cash_transfers (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_request_id UUID NOT NULL,
            source_subaccount_id UUID NOT NULL
                REFERENCES account_subaccounts(id) ON DELETE CASCADE,
            destination_subaccount_id UUID NOT NULL
                REFERENCES account_subaccounts(id) ON DELETE CASCADE,
            source_amount NUMERIC(20, 4) NOT NULL,
            source_currency currency_code NOT NULL,
            destination_amount NUMERIC(20, 4) NOT NULL,
            destination_currency currency_code NOT NULL,
            transfer_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cash_transfers_request UNIQUE (user_id, client_request_id),
            CONSTRAINT ck_cash_transfers_source_positive CHECK (source_amount > 0),
            CONSTRAINT ck_cash_transfers_destination_positive CHECK (destination_amount > 0),
            CONSTRAINT ck_cash_transfers_distinct_wallets
                CHECK (source_subaccount_id <> destination_subaccount_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_cash_transfers_user_date ON cash_transfers (user_id, transfer_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cash_transfers")
