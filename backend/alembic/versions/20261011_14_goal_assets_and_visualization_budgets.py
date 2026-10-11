"""Link accounts, holdings and deposits to goals; add visualization budgets.

Revision ID: 20261011_14
Revises: 20261011_13
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_14"
down_revision: str | None = "20261011_13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "financial_goals",
        sa.Column("visualization_budget_amount", sa.Numeric(20, 4), nullable=True),
    )
    op.add_column(
        "financial_goals",
        sa.Column("visualization_budget_period", sa.String(8), nullable=True),
    )
    op.create_check_constraint(
        "ck_goals_visualization_budget_pair",
        "financial_goals",
        "(visualization_budget_amount IS NULL) = (visualization_budget_period IS NULL)",
    )
    op.create_check_constraint(
        "ck_goals_visualization_budget_period",
        "financial_goals",
        "visualization_budget_period IS NULL OR "
        "visualization_budget_period IN ('monthly', 'yearly')",
    )
    op.add_column(
        "fixed_deposits",
        sa.Column("source_subaccount_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_fixed_deposits_source_subaccount",
        "fixed_deposits",
        "account_subaccounts",
        ["source_subaccount_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "fixed_deposits",
        sa.Column("period_months", sa.Integer(), nullable=False, server_default="12"),
    )
    op.execute(
        """
        UPDATE fixed_deposits
        SET period_months = GREATEST(
            1,
            (EXTRACT(YEAR FROM maturity_date) - EXTRACT(YEAR FROM start_date))::integer * 12
            + (EXTRACT(MONTH FROM maturity_date) - EXTRACT(MONTH FROM start_date))::integer
        )
        """
    )
    op.alter_column("fixed_deposits", "period_months", server_default=None)
    op.create_table(
        "goal_account_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["financial_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts_brokers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("goal_id", "account_id", name="uq_goal_account_links_goal_account"),
    )
    op.create_index("ix_goal_account_links_user_id", "goal_account_links", ["user_id"])
    op.create_table(
        "goal_holding_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("holding_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["financial_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["holding_id"], ["holdings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("holding_id", name="uq_goal_holding_allocations_holding"),
    )
    op.create_index("ix_goal_holding_allocations_user_id", "goal_holding_allocations", ["user_id"])
    op.create_table(
        "goal_deposit_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("fixed_deposit_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["financial_goals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fixed_deposit_id"], ["fixed_deposits.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fixed_deposit_id", name="uq_goal_deposit_allocations_deposit"),
    )
    op.create_index("ix_goal_deposit_allocations_user_id", "goal_deposit_allocations", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_goal_deposit_allocations_user_id", table_name="goal_deposit_allocations")
    op.drop_table("goal_deposit_allocations")
    op.drop_index("ix_goal_holding_allocations_user_id", table_name="goal_holding_allocations")
    op.drop_table("goal_holding_allocations")
    op.drop_index("ix_goal_account_links_user_id", table_name="goal_account_links")
    op.drop_table("goal_account_links")
    op.drop_constraint(
        "fk_fixed_deposits_source_subaccount", "fixed_deposits", type_="foreignkey"
    )
    op.drop_column("fixed_deposits", "period_months")
    op.drop_column("fixed_deposits", "source_subaccount_id")
    op.drop_constraint(
        "ck_goals_visualization_budget_period", "financial_goals", type_="check"
    )
    op.drop_constraint("ck_goals_visualization_budget_pair", "financial_goals", type_="check")
    op.drop_column("financial_goals", "visualization_budget_period")
    op.drop_column("financial_goals", "visualization_budget_amount")
