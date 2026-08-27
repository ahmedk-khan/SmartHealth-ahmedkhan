from alembic import op


revision = "010_add_booking_statuses"
down_revision = "009_add_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'REQUESTED'")
        op.execute("ALTER TYPE appointmentstatus ADD VALUE IF NOT EXISTS 'SLOT_RESERVED'")


def downgrade() -> None:
    pass