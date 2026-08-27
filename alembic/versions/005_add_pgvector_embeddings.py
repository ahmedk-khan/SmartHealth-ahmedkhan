from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = "005_add_pgvector_embeddings"
down_revision = "004_add_services_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("content_chunks", sa.Column("embedding", Vector(1024), nullable=True))
    op.create_index(
        "ix_content_chunks_embedding_hnsw",
        "content_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_content_chunks_embedding_hnsw", table_name="content_chunks")
    op.drop_column("content_chunks", "embedding")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP EXTENSION IF EXISTS vector")