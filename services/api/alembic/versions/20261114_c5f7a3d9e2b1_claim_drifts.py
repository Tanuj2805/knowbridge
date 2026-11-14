"""drift log: what happened to claims when the evidence they cite changed at its source

Revision ID: c5f7a3d9e2b1
Revises: b8e1f4a2c6d9
Create Date: 2026-11-14 20:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c5f7a3d9e2b1"
down_revision: str | None = "b8e1f4a2c6d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "claim_drifts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("evidence_units.id", ondelete="SET NULL")),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("change", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False, server_default=""),
        sa.Column("before", sa.Text(), nullable=False, server_default=""),
        sa.Column("after", sa.Text(), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("stance_before", sa.String(16), nullable=False, server_default=""),
        sa.Column("grade_before", sa.String(32), nullable=False, server_default=""),
        sa.Column("grade_after", sa.String(32), nullable=False, server_default=""),
        sa.Column("reopened", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )
    op.create_index("ix_claim_drifts_project_detected", "claim_drifts", ["project_id", "detected_at"])
    op.create_index("ix_claim_drifts_claim_id", "claim_drifts", ["claim_id"])
    op.create_index("ix_claim_drifts_outcome", "claim_drifts", ["outcome"])


def downgrade() -> None:
    op.drop_table("claim_drifts")
