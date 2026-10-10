"""Add provider-backed market quotes and FX rates.

Revision ID: 20261010_04
Revises: 20261010_03
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261010_04"
down_revision: str | None = "20261010_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE currency_code ADD VALUE IF NOT EXISTS 'RON'")
    op.execute(
        "ALTER TABLE instruments "
        "ADD COLUMN IF NOT EXISTS instrument_type VARCHAR(16) NOT NULL DEFAULT 'STOCK'"
    )
    op.execute(
        "ALTER TABLE instruments "
        "ADD COLUMN IF NOT EXISTS exchange VARCHAR(80) NOT NULL DEFAULT ''"
    )
    op.execute("ALTER TABLE instruments DROP CONSTRAINT IF EXISTS instruments_symbol_key")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_instruments_symbol_mic'
                  AND conrelid = 'instruments'::regclass
            ) THEN
                ALTER TABLE instruments
                    ADD CONSTRAINT uq_instruments_symbol_mic UNIQUE (symbol, mic);
            END IF;
        END
        $$
        """
    )
    op.execute(
        "ALTER TABLE market_prices_cache "
        "ADD COLUMN IF NOT EXISTS is_market_open BOOLEAN"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market_fx_rates (
            id SERIAL PRIMARY KEY,
            base_currency currency_code NOT NULL,
            quote_currency currency_code NOT NULL,
            rate NUMERIC(24, 12) NOT NULL CHECK (rate > 0),
            provider VARCHAR(40) NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            previous_rate NUMERIC(24, 12),
            CONSTRAINT uq_market_fx_rates_pair_provider_observed
                UNIQUE (base_currency, quote_currency, provider, observed_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_market_fx_latest "
        "ON market_fx_rates (base_currency, quote_currency, received_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_market_fx_latest")
    op.execute("DROP TABLE IF EXISTS market_fx_rates")
    op.execute("ALTER TABLE market_prices_cache DROP COLUMN IF EXISTS is_market_open")
    op.execute("ALTER TABLE instruments DROP CONSTRAINT IF EXISTS uq_instruments_symbol_mic")
    op.execute("ALTER TABLE instruments ADD CONSTRAINT instruments_symbol_key UNIQUE (symbol)")
    op.execute("ALTER TABLE instruments DROP COLUMN IF EXISTS exchange")
    op.execute("ALTER TABLE instruments DROP COLUMN IF EXISTS instrument_type")
