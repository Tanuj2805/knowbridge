"""handovers get a kind: a real handover, or a knowledge capture started from the Risk Radar

Revision ID: a4d2e9c7b315
Revises: f3c8d2a1b6e4
Create Date: 2026-11-14 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d2e9c7b315"
down_revision: str | None = "f3c8d2a1b6e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("handovers", sa.Column("kind", sa.String(16), nullable=False, server_default="handover"))


def downgrade() -> None:
    op.drop_column("handovers", "kind")
