"""claim skeptic verdict

Revision ID: 5b1e7c2d9f30
Revises: 2cab4efbea08
Create Date: 2026-11-09 12:30:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b1e7c2d9f30"
down_revision: str | None = "2cab4efbea08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("skeptic", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("claims", "skeptic")
