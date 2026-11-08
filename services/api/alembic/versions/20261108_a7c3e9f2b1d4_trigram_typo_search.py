"""trigram index for typo-tolerant search

Revision ID: a7c3e9f2b1d4
Revises: 219e99f94f99
Create Date: 2026-11-08
"""
from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e9f2b1d4"
down_revision: str | None = "219e99f94f99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_evidence_text_trgm ON evidence_units USING gin (text gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evidence_text_trgm")
