from alembic import op
import sqlalchemy as sa


revision = "012_rebook_cancelled_slots"
down_revision = "011_add_outbox_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        metadata = sa.MetaData()
        appointments = sa.Table("appointments", metadata, autoload_with=op.get_bind())
        unique_constraint = next(
            (constraint for constraint in appointments.constraints
             if isinstance(constraint, sa.UniqueConstraint)
             and [column.name for column in constraint.columns] == ["slot_id"]),
            None,
        )
        if unique_constraint is not None:
            appointments.constraints.remove(unique_constraint)
            with op.batch_alter_table("appointments", copy_from=appointments):
                pass
        return
    with op.batch_alter_table("appointments", schema=None) as batch_op:
        batch_op.drop_constraint("appointments_slot_id_key", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("appointments", schema=None) as batch_op:
        batch_op.create_unique_constraint("appointments_slot_id_key", ["slot_id"])
