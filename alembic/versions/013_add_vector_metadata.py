from alembic import op
import sqlalchemy as sa


revision = "013_add_vector_metadata"
down_revision = "012_rebook_cancelled_slots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_chunks", sa.Column("department", sa.String(length=120), nullable=False, server_default=""))
    op.add_column("content_chunks", sa.Column("specialty", sa.String(length=140), nullable=True))
    op.add_column("content_chunks", sa.Column("published", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(
        """
        UPDATE content_chunks
        SET department = (
            SELECT departments.name
            FROM services
            JOIN departments ON departments.id = services.department_id
            WHERE services.id = content_chunks.service_id
        ),
        specialty = (
            SELECT services.specialty
            FROM services
            WHERE services.id = content_chunks.service_id
        ),
        published = (
            SELECT services.is_published
            FROM services
            WHERE services.id = content_chunks.service_id
        )
        """
    )


def downgrade() -> None:
    op.drop_column("content_chunks", "published")
    op.drop_column("content_chunks", "specialty")
    op.drop_column("content_chunks", "department")