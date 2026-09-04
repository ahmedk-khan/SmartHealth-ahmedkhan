from alembic import op
import sqlalchemy as sa


revision = "023_update_embedding_dimensions"
down_revision = "022_reconcile_model_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        existing_embeddings = bind.execute(
            sa.text("SELECT COUNT(*) FROM content_chunks WHERE embedding IS NOT NULL")
        ).scalar_one()
        if existing_embeddings:
            raise RuntimeError(
                "Refusing to change embedding dimensions while embeddings exist. "
                "Run the service re-embedding job with the new model/dimensions, "
                "verify the backfill, then apply this migration."
            )
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
    """Refuse this lossy downgrade and require restoring embeddings from backup.

    The upgrade converts embeddings with ``USING NULL`` and therefore
    destroys their values. A prior vector dimension cannot be recovered
    from the database, and truncating vectors would also be lossy.
    """
    if op.get_bind().dialect.name == "postgresql":
        raise RuntimeError("Refusing to downgrade vector dimensions because existing embeddings would be lost")