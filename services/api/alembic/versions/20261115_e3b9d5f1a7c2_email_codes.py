"""one-time email codes: count wrong tries per code

Revision ID: e3b9d5f1a7c2
Revises: d7a1c4e8f2b6
Create Date: 2026-11-15 14:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b9d5f1a7c2"
down_revision: str | None = "d7a1c4e8f2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_tokens", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("email_tokens", "attempts")
