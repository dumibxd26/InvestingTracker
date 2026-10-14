"""Add tax residency, broker tax method, and instrument tax domicile.

Revision ID: 20261014_21
Revises: 20261014_20
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_21"
down_revision: str | None = "20261014_20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN tax_residence_country_code VARCHAR(2),
            ADD COLUMN tax_year INTEGER,
            ADD COLUMN tax_minimum_monthly_wage NUMERIC(20, 4),
            ADD CONSTRAINT ck_users_tax_residence_country_code
                CHECK (
                    tax_residence_country_code IS NULL
                    OR tax_residence_country_code ~ '^[A-Z]{2}$'
                ),
            ADD CONSTRAINT ck_users_tax_year
                CHECK (tax_year IS NULL OR tax_year BETWEEN 2000 AND 2100),
            ADD CONSTRAINT ck_users_tax_country_year_pair
                CHECK (
                    (tax_residence_country_code IS NULL) = (tax_year IS NULL)
                ),
            ADD CONSTRAINT ck_users_tax_minimum_wage_positive
                CHECK (
                    tax_minimum_monthly_wage IS NULL
                    OR tax_minimum_monthly_wage > 0
                ),
            ADD CONSTRAINT ck_users_tax_minimum_wage_requires_tax_profile
                CHECK (
                    tax_minimum_monthly_wage IS NULL
                    OR tax_residence_country_code IS NOT NULL
                )
        """
    )
    op.execute(
        """
        ALTER TABLE accounts_brokers
            ADD COLUMN broker_country_code VARCHAR(2),
            ADD COLUMN tax_reporting_method VARCHAR(32) NOT NULL DEFAULT 'legacy_manual',
            ADD CONSTRAINT ck_accounts_brokers_broker_country_code
                CHECK (
                    broker_country_code IS NULL
                    OR broker_country_code ~ '^[A-Z]{2}$'
                ),
            ADD CONSTRAINT ck_accounts_brokers_tax_reporting_method
                CHECK (
                    tax_reporting_method IN (
                        'legacy_manual',
                        'withholding_agent',
                        'annual_self_assessment',
                        'tax_exempt'
                    )
                )
        """
    )
    op.execute(
        """
        ALTER TABLE instruments
            ADD COLUMN tax_domicile_country_code VARCHAR(2),
            ADD CONSTRAINT ck_instruments_tax_domicile_country_code
                CHECK (
                    tax_domicile_country_code IS NULL
                    OR tax_domicile_country_code ~ '^[A-Z]{2}$'
                )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE instruments
            DROP CONSTRAINT ck_instruments_tax_domicile_country_code,
            DROP COLUMN tax_domicile_country_code
        """
    )
    op.execute(
        """
        ALTER TABLE accounts_brokers
            DROP CONSTRAINT ck_accounts_brokers_tax_reporting_method,
            DROP CONSTRAINT ck_accounts_brokers_broker_country_code,
            DROP COLUMN tax_reporting_method,
            DROP COLUMN broker_country_code
        """
    )
    op.execute(
        """
        ALTER TABLE users
            DROP CONSTRAINT ck_users_tax_minimum_wage_positive,
            DROP CONSTRAINT ck_users_tax_minimum_wage_requires_tax_profile,
            DROP CONSTRAINT ck_users_tax_country_year_pair,
            DROP CONSTRAINT ck_users_tax_year,
            DROP CONSTRAINT ck_users_tax_residence_country_code,
            DROP COLUMN tax_minimum_monthly_wage,
            DROP COLUMN tax_year,
            DROP COLUMN tax_residence_country_code
        """
    )
