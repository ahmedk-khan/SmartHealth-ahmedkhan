from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006_add_service_chunk_metadata"
down_revision = "005_add_pgvector_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("specialty", sa.String(length=140), nullable=True))
    op.add_column("services", sa.Column("preparation_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("services", "preparation_instructions")
    op.drop_column("services", "specialty")