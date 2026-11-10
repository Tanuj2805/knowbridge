"""gap question meta

Revision ID: 8d4f0a6c1e52
Revises: 5b1e7c2d9f30
Create Date: 2026-11-09 15:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d4f0a6c1e52"
down_revision: str | None = "5b1e7c2d9f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gap_questions", sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}",
                                             nullable=False))
    op.add_column("gap_questions", sa.Column("position", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("gap_questions", "position")
    op.drop_column("gap_questions", "meta")
