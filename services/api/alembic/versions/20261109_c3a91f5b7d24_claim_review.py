"""claim review

Revision ID: c3a91f5b7d24
Revises: 8d4f0a6c1e52
Create Date: 2026-11-09 18:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3a91f5b7d24"
down_revision: str | None = "8d4f0a6c1e52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column("claims", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("claims", sa.Column("review_note", sa.Text(), server_default="", nullable=False))
    op.create_foreign_key("fk_claims_reviewed_by_users", "claims", "users", ["reviewed_by"], ["id"],
                          ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_claims_reviewed_by_users", "claims", type_="foreignkey")
    op.drop_column("claims", "review_note")
    op.drop_column("claims", "reviewed_at")
    op.drop_column("claims", "reviewed_by")
