from alembic import op
import sqlalchemy as sa


revision = "014_add_chunk_content_hash"
down_revision = "013_add_vector_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_chunks", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_content_chunks_content_hash"), "content_chunks", ["content_hash"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_content_chunks_content_hash"), table_name="content_chunks")
    op.drop_column("content_chunks", "content_hash")