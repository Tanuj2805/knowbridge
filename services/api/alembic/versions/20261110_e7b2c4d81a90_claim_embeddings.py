"""claim embeddings, for asking questions of a project (RAG)

Revision ID: e7b2c4d81a90
Revises: c3a91f5b7d24
Create Date: 2026-11-10 10:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "e7b2c4d81a90"
down_revision: str | None = "c3a91f5b7d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    op.add_column("claims", sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True))
    op.add_column("claims", sa.Column("embedding_model", sa.String(120), nullable=True))
    op.create_index("ix_claims_embedding_model", "claims", ["embedding_model"])
    op.create_index(
        "ix_claims_embedding",
        "claims",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_claims_embedding", table_name="claims")
    op.drop_index("ix_claims_embedding_model", table_name="claims")
    op.drop_column("claims", "embedding_model")
    op.drop_column("claims", "embedding")
