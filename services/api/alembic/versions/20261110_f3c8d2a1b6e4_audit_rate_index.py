"""index the audit log by person, action and time (it counts requests for rate limits)

Revision ID: f3c8d2a1b6e4
Revises: e7b2c4d81a90
Create Date: 2026-11-10 14:00:00.000000
"""
from collections.abc import Sequence

from alembic import op

revision: str = "f3c8d2a1b6e4"
down_revision: str | None = "e7b2c4d81a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_actor_action_at", "audit_log", ["actor_id", "action", "at"])


def downgrade() -> None:
    op.drop_index("ix_audit_actor_action_at", table_name="audit_log")
