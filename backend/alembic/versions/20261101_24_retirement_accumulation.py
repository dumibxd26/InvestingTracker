"""Persist retirement scenarios and private, licensed monthly history."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261101_24"
down_revision: str | None = "20261018_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("financial_goals") as batch:
        batch.add_column(sa.Column("retirement_settings", sa.JSON(), nullable=True))
    op.create_table(
        "retirement_history",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("source", sa.String(500), nullable=False),
        sa.Column("license", sa.String(200), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retirement_history_user_id", "retirement_history", ["user_id"])


def downgrade() -> None:
    op.drop_table("retirement_history")
    with op.batch_alter_table("financial_goals") as batch:
        batch.drop_column("retirement_settings")
