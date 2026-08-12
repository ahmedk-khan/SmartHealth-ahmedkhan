from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "003_add_billings"
down_revision = "002_add_appointments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "billings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("appointment_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "status",
            sa.Enum("APPROVED", "DECLINED", "PENDING", name="billingstatus"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("appointment_id"),
    )
    op.create_index(op.f("ix_billings_id"), "billings", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_billings_id"), table_name="billings")
    op.drop_table("billings")
