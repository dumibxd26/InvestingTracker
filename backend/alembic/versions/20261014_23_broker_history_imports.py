"""Add immutable broker-import batches and transaction history.

Revision ID: 20261014_23
Revises: 20261014_22
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_23"
down_revision: str | None = "20261014_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE broker_import_batches (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            provider_code VARCHAR(40) NOT NULL,
            content_sha256 VARCHAR(64) NOT NULL,
            source_format VARCHAR(16) NOT NULL,
            stocks_etfs_only BOOLEAN NOT NULL DEFAULT FALSE,
            record_count INTEGER NOT NULL,
            duplicate_count INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_broker_import_batches_file
                UNIQUE (user_id, account_id, provider_code, content_sha256),
            CONSTRAINT ck_broker_import_batches_sha256
                CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_broker_import_batches_count
                CHECK (record_count >= 0 AND duplicate_count >= 0)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_broker_import_batches_user_id
        ON broker_import_batches (user_id)
        """
    )
    op.execute(
        """
        CREATE TABLE broker_transactions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            account_id UUID NOT NULL REFERENCES accounts_brokers(id) ON DELETE CASCADE,
            import_batch_id UUID NOT NULL
                REFERENCES broker_import_batches(id) ON DELETE CASCADE,
            provider_code VARCHAR(40) NOT NULL,
            source_event_id VARCHAR(120) NOT NULL,
            event_type VARCHAR(24) NOT NULL,
            source_sheet VARCHAR(80) NOT NULL,
            broker_reference VARCHAR(100),
            event_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            opened_at TIMESTAMP WITHOUT TIME ZONE,
            closed_at TIMESTAMP WITHOUT TIME ZONE,
            symbol VARCHAR(40),
            description VARCHAR(240),
            direction VARCHAR(16),
            asset_type VARCHAR(40),
            quantity NUMERIC(24, 10),
            open_price NUMERIC(24, 10),
            close_price NUMERIC(24, 10),
            amount NUMERIC(24, 8),
            currency_code VARCHAR(3) NOT NULL,
            commission NUMERIC(24, 8),
            swap NUMERIC(24, 8),
            taxes NUMERIC(24, 8),
            reported_profit NUMERIC(24, 8),
            balance_after NUMERIC(24, 8),
            created_at TIMESTAMPTZ NOT NULL,
            CONSTRAINT uq_broker_transactions_source_event
                UNIQUE (user_id, account_id, provider_code, source_event_id),
            CONSTRAINT ck_broker_transactions_event_type
                CHECK (event_type IN ('closed_position', 'cash_operation')),
            CONSTRAINT ck_broker_transactions_currency_code
                CHECK (currency_code ~ '^[A-Z]{3}$'),
            CONSTRAINT ck_broker_transactions_closed_position_fields
                CHECK (
                    event_type <> 'closed_position'
                    OR (
                        opened_at IS NOT NULL
                        AND closed_at IS NOT NULL
                        AND quantity IS NOT NULL
                        AND quantity > 0
                        AND open_price IS NOT NULL
                        AND open_price > 0
                        AND close_price IS NOT NULL
                        AND close_price > 0
                    )
                ),
            CONSTRAINT ck_broker_transactions_cash_operation_fields
                CHECK (event_type <> 'cash_operation' OR amount IS NOT NULL)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_broker_transactions_account_event_date
        ON broker_transactions (account_id, event_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE broker_transactions")
    op.execute("DROP TABLE broker_import_batches")
