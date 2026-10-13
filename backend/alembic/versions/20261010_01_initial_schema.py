"""Create missing InvestingTracker tables without modifying existing records.

Revision ID: 20261010_01
Revises:
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import app.models  # noqa: F401
from alembic import op
from app.database import Base

revision: str = "20261010_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    pass
