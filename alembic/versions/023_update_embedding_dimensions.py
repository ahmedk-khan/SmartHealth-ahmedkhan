from alembic import op


revision = "023_update_embedding_dimensions"
down_revision = "022_reconcile_model_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_content_chunks_embedding_hnsw", table_name="content_chunks")
        op.execute("ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(1024) USING NULL")
        op.create_index(
            "ix_content_chunks_embedding_hnsw",
            "content_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("ix_content_chunks_embedding_hnsw", table_name="content_chunks")
        op.execute("ALTER TABLE content_chunks ALTER COLUMN embedding TYPE vector(384) USING NULL")
        op.create_index(
            "ix_content_chunks_embedding_hnsw",
            "content_chunks",
            ["embedding"],
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        )