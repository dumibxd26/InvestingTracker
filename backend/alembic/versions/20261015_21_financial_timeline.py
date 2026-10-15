"""Add forecast-only financial timelines and remove goal priority.

Revision ID: 20261015_21
Revises: 20261014_23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261015_21"
down_revision: str | None = "20261014_23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "financial_plans",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("configuration", sa.JSON(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "INSERT INTO financial_plans (user_id, configuration) "
            "SELECT id, json_build_object("
            "'anchor_date', CURRENT_DATE::text, 'annual_inflation_rate', '0.03', "
            "'income_sources', '[]'::json, 'inflation_changes', '[]'::json, "
            "'monthly_expenses', NULL, 'expenses_currency', base_currency::text) FROM users"
        )
    else:
        op.execute(
            "INSERT INTO financial_plans (user_id, configuration) "
            "SELECT id, json_object("
            "'anchor_date', date('now'), 'annual_inflation_rate', '0.03', "
            "'income_sources', json('[]'), 'inflation_changes', json('[]'), "
            "'monthly_expenses', NULL, 'expenses_currency', base_currency) FROM users"
        )
    op.add_column(
        "financial_goals",
        sa.Column("target_money_basis", sa.String(10), nullable=False, server_default="real"),
    )
    op.add_column(
        "financial_goals", sa.Column("annual_inflation_rate", sa.Numeric(12, 8), nullable=True)
    )
    op.add_column("financial_goals", sa.Column("contribution_rules", sa.JSON(), nullable=True))
    op.execute(
        "UPDATE allocation_policies SET funding_rule = 'proportional' "
        "WHERE funding_rule = 'priority_first'"
    )
    op.execute(
        "UPDATE recommendations SET funding_rule = 'proportional' "
        "WHERE funding_rule = 'priority_first'"
    )
    op.drop_column("financial_goals", "priority")


def downgrade() -> None:
    op.add_column(
        "financial_goals", sa.Column("priority", sa.Integer(), nullable=False, server_default="3")
    )
    op.drop_column("financial_goals", "contribution_rules")
    op.drop_column("financial_goals", "annual_inflation_rate")
    op.drop_column("financial_goals", "target_money_basis")
    op.drop_table("financial_plans")
