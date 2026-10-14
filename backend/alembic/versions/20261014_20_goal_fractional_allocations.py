"""Allow fractional allocations of a holding or deposit across several goals.

Revision ID: 20261014_20
Revises: 20261011_19
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261014_20"
down_revision: str | None = "20261011_19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE goal_holding_allocations
            ADD COLUMN allocated_percentage NUMERIC(8, 4) NOT NULL DEFAULT 100,
            DROP CONSTRAINT uq_goal_holding_allocations_holding,
            ADD CONSTRAINT uq_goal_holding_allocations_goal_holding
                UNIQUE (goal_id, holding_id),
            ADD CONSTRAINT ck_goal_holding_allocations_percentage
                CHECK (allocated_percentage > 0 AND allocated_percentage <= 100)
        """
    )
    op.execute(
        """
        ALTER TABLE goal_deposit_allocations
            ADD COLUMN allocated_percentage NUMERIC(8, 4) NOT NULL DEFAULT 100,
            DROP CONSTRAINT uq_goal_deposit_allocations_deposit,
            ADD CONSTRAINT uq_goal_deposit_allocations_goal_deposit
                UNIQUE (goal_id, fixed_deposit_id),
            ADD CONSTRAINT ck_goal_deposit_allocations_percentage
                CHECK (allocated_percentage > 0 AND allocated_percentage <= 100)
        """
    )


def downgrade() -> None:
    # Keep the earliest link per holding or deposit so the single-goal constraints can return.
    op.execute(
        """
        DELETE FROM goal_holding_allocations a
        USING goal_holding_allocations b
        WHERE a.holding_id = b.holding_id AND a.id > b.id
        """
    )
    op.execute(
        """
        DELETE FROM goal_deposit_allocations a
        USING goal_deposit_allocations b
        WHERE a.fixed_deposit_id = b.fixed_deposit_id AND a.id > b.id
        """
    )
    op.execute(
        """
        ALTER TABLE goal_holding_allocations
            DROP CONSTRAINT ck_goal_holding_allocations_percentage,
            DROP CONSTRAINT uq_goal_holding_allocations_goal_holding,
            DROP COLUMN allocated_percentage,
            ADD CONSTRAINT uq_goal_holding_allocations_holding UNIQUE (holding_id)
        """
    )
    op.execute(
        """
        ALTER TABLE goal_deposit_allocations
            DROP CONSTRAINT ck_goal_deposit_allocations_percentage,
            DROP CONSTRAINT uq_goal_deposit_allocations_goal_deposit,
            DROP COLUMN allocated_percentage,
            ADD CONSTRAINT uq_goal_deposit_allocations_deposit UNIQUE (fixed_deposit_id)
        """
    )
