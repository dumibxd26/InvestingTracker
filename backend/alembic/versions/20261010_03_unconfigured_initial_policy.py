"""Allow new users to choose their initial goal funding rule.

Revision ID: 20261010_03
Revises: 20261010_02
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261010_03"
down_revision: str | None = "20261010_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE allocation_policies ALTER COLUMN funding_rule DROP NOT NULL")


def downgrade() -> None:
    op.execute(
        "UPDATE allocation_policies SET funding_rule = 'priority_first' WHERE funding_rule IS NULL"
    )
    op.execute("ALTER TABLE allocation_policies ALTER COLUMN funding_rule SET NOT NULL")
