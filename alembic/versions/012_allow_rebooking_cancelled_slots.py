from alembic import op
import sqlalchemy as sa


revision = "012_rebook_cancelled_slots"
down_revision = "011_add_outbox_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("appointments_slot_id_key", "appointments", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("appointments_slot_id_key", "appointments", ["slot_id"])
