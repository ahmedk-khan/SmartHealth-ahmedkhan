from alembic import op
import sqlalchemy as sa


revision = "016_add_booking_key"
down_revision = "015_add_service_price"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("appointments", sa.Column("booking_key", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_appointments_booking_key"), "appointments", ["booking_key"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_appointments_booking_key"), table_name="appointments")
    op.drop_column("appointments", "booking_key")