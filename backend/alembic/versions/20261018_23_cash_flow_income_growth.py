"""Add expected salary raises and salary-linked annual cash-flow bonuses.

Revision ID: 20261018_23
Revises: 20261015_22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261018_23"
down_revision: str | None = "20261015_22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cash_flow_schedules") as batch:
        batch.add_column(
            sa.Column("annual_growth_rate", sa.Numeric(12, 8), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("salary_schedule_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("salary_percentage", sa.Numeric(12, 8), nullable=True))
        batch.create_foreign_key(
            "fk_cash_flow_schedules_salary",
            "cash_flow_schedules",
            ["salary_schedule_id"],
            ["id"],
        )
        batch.create_check_constraint(
            "ck_cash_flow_schedules_growth_rate",
            "annual_growth_rate >= -0.5 AND annual_growth_rate <= 1",
        )
        batch.create_check_constraint(
            "ck_cash_flow_schedules_salary_bonus",
            "(salary_schedule_id IS NULL AND salary_percentage IS NULL) OR "
            "(salary_schedule_id IS NOT NULL AND salary_percentage IS NOT NULL "
            "AND salary_percentage > 0 AND salary_percentage <= 1 "
            "AND kind = 'bonus' AND recurrence = 'annual' AND annual_growth_rate = 0)",
        )


def downgrade() -> None:
    with op.batch_alter_table("cash_flow_schedules") as batch:
        batch.drop_constraint("ck_cash_flow_schedules_salary_bonus", type_="check")
        batch.drop_constraint("ck_cash_flow_schedules_growth_rate", type_="check")
        batch.drop_constraint("fk_cash_flow_schedules_salary", type_="foreignkey")
        batch.drop_column("salary_percentage")
        batch.drop_column("salary_schedule_id")
        batch.drop_column("annual_growth_rate")
