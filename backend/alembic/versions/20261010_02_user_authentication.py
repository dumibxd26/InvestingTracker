"""Add username/password profile fields and persistent login sessions.

Revision ID: 20261010_02
Revises: 20261010_01
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261010_02"
down_revision: str | None = "20261010_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(32)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash VARCHAR(512)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS usd_per_eur NUMERIC(20, 10)")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS login_sessions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_digest VARCHAR(64) NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_login_sessions_user_id ON login_sessions (user_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_login_sessions_expires_at ON login_sessions (expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS login_sessions")
    op.execute("DROP INDEX IF EXISTS ix_users_username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS usd_per_eur")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_hash")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")
