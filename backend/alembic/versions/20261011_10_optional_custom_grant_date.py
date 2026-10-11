"""Allow imported custom-tranche awards without a known grant date.

Revision ID: 20261011_10
Revises: 20261011_09
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261011_10"
down_revision: str | None = "20261011_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE vesting_grants ALTER COLUMN grant_date DROP NOT NULL")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM vesting_grants WHERE grant_date IS NULL) THEN
                RAISE EXCEPTION
                    'Cannot require grant_date while custom awards have an unknown date';
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE vesting_grants ALTER COLUMN grant_date SET NOT NULL")
