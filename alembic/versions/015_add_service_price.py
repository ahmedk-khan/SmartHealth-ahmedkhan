from alembic import op
import sqlalchemy as sa


revision = "015_add_service_price"
down_revision = "014_add_chunk_content_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("services", sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0.00"))


def downgrade() -> None:
    op.drop_column("services", "price")