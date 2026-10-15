"""Record spending from bank-account wallets.

Revision ID: 20261015_22
Revises: 20261015_21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261015_22"
down_revision: str | None = "20261015_21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE cash_spends (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            client_request_id UUID NOT NULL,
            subaccount_id UUID NOT NULL
                REFERENCES account_subaccounts(id) ON DELETE CASCADE,
            amount NUMERIC(20, 4) NOT NULL,
            currency currency_code NOT NULL,
            spend_date DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_cash_spends_request UNIQUE (user_id, client_request_id),
            CONSTRAINT ck_cash_spends_amount_positive CHECK (amount > 0)
        )
        """
    )
    op.execute("CREATE INDEX ix_cash_spends_user_date ON cash_spends (user_id, spend_date)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS cash_spends")
