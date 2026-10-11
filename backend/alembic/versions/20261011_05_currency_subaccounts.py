"""Move account balances into per-currency sub-accounts.

Revision ID: 20261011_05
Revises: 20261010_04
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_05"
down_revision: str | None = "20261010_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_subaccounts (
            id UUID PRIMARY KEY,
            account_id UUID NOT NULL REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            currency currency_code NOT NULL,
            cash_balance NUMERIC(20, 4) NOT NULL DEFAULT 0,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            CONSTRAINT uq_account_subaccounts_currency UNIQUE (account_id, currency)
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'accounts_brokers' AND column_name = 'currency'
            ) THEN
                INSERT INTO account_subaccounts (id, account_id, currency, cash_balance, is_primary)
                SELECT id, id, currency, cash_balance, TRUE
                FROM accounts_brokers
                ON CONFLICT (account_id, currency) DO NOTHING;
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_account_subaccounts_currency'
                  AND conrelid = 'account_subaccounts'::regclass
            ) THEN
                ALTER TABLE account_subaccounts
                    ADD CONSTRAINT uq_account_subaccounts_currency UNIQUE (account_id, currency);
            END IF;
        END
        $$
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_account_subaccounts_primary "
        "ON account_subaccounts (account_id) WHERE is_primary"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'cash_flows' AND column_name = 'subaccount_id'
            ) THEN
                ALTER TABLE cash_flows
                    ADD COLUMN subaccount_id UUID
                    REFERENCES account_subaccounts(id) ON DELETE SET NULL;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'holdings' AND column_name = 'funding_subaccount_id'
            ) THEN
                ALTER TABLE holdings ADD COLUMN funding_subaccount_id UUID
                    REFERENCES account_subaccounts(id) ON DELETE CASCADE;
            END IF;
        END
        $$
        """
    )
    op.execute(
        """
        UPDATE cash_flows AS flow
        SET subaccount_id = subaccount.id
        FROM account_subaccounts AS subaccount
        WHERE flow.account_id = subaccount.account_id
          AND flow.currency = subaccount.currency
          AND flow.subaccount_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE holdings AS holding
        SET funding_subaccount_id = subaccount.id
        FROM account_subaccounts AS subaccount
        WHERE holding.account_id = subaccount.account_id
          AND subaccount.is_primary
          AND holding.funding_subaccount_id IS NULL
        """
    )
    op.execute(
        "ALTER TABLE holdings ALTER COLUMN funding_subaccount_id SET NOT NULL"
    )
    op.execute("ALTER TABLE accounts_brokers DROP COLUMN IF EXISTS cash_balance")
    op.execute("ALTER TABLE accounts_brokers DROP COLUMN IF EXISTS currency")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE accounts_brokers "
        "ADD COLUMN IF NOT EXISTS currency currency_code"
    )
    op.execute(
        "ALTER TABLE accounts_brokers "
        "ADD COLUMN IF NOT EXISTS cash_balance NUMERIC(20, 4) NOT NULL DEFAULT 0"
    )
    op.execute(
        """
        UPDATE accounts_brokers AS account
        SET currency = subaccount.currency,
            cash_balance = subaccount.cash_balance
        FROM account_subaccounts AS subaccount
        WHERE account.id = subaccount.account_id AND subaccount.is_primary
        """
    )
    op.execute("ALTER TABLE accounts_brokers ALTER COLUMN currency SET NOT NULL")
    op.execute("ALTER TABLE cash_flows DROP COLUMN IF EXISTS subaccount_id")
    op.execute("ALTER TABLE holdings DROP COLUMN IF EXISTS funding_subaccount_id")
    op.execute("DROP INDEX IF EXISTS uq_account_subaccounts_primary")
    op.execute("DROP TABLE IF EXISTS account_subaccounts")
