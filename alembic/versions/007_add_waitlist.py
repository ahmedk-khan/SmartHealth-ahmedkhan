from alembic import op
import sqlalchemy as sa


revision = "007_add_waitlist"
down_revision = "006_add_service_chunk_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slot_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("WAITING", "PROMOTED", "CANCELLED", name="waitliststatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["slots.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slot_id", "patient_id", name="uq_waitlist_slot_patient"),
    )
    op.create_index(op.f("ix_waitlist_entries_id"), "waitlist_entries", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_waitlist_entries_id"), table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    sa.Enum(name="waitliststatus").drop(op.get_bind(), checkfirst=True)