from alembic import op
import sqlalchemy as sa


revision = "008_complete_demo_schema"
down_revision = "007_add_waitlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    visit_status = sa.Enum("NOT_STARTED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", name="visitstatus")
    visit_status.create(op.get_bind(), checkfirst=True)
    op.add_column("appointments", sa.Column("visit_status", sa.Enum("NOT_STARTED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", name="visitstatus"), nullable=False, server_default="NOT_STARTED"))
    op.add_column("providers", sa.Column("specialty", sa.String(length=140), nullable=True))
    op.add_column("content_chunks", sa.Column("source_type", sa.String(length=80), nullable=False, server_default="service"))
    op.add_column("content_chunks", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("content_chunks", sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE content_chunks SET source_id = service_id WHERE source_id IS NULL")
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("content_chunks", "source_id", nullable=False, server_default=None)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE servicestatus ADD VALUE IF NOT EXISTS 'PUBLISH_FAILED'")
    for table in ("analytics_processed_events", "analytics_appointments_daily", "analytics_services_daily"):
        if table == "analytics_processed_events":
            op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.String(128), unique=True, nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("topic", sa.String(120), nullable=False), sa.Column("payload", sa.JSON(), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False))
        elif table == "analytics_appointments_daily":
            op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_date", sa.String(10), nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("appointment_id", sa.Integer(), nullable=False), sa.Column("patient_id", sa.Integer()), sa.Column("provider_id", sa.Integer()), sa.Column("service_id", sa.Integer()), sa.Column("slot_id", sa.Integer()), sa.Column("status", sa.String(40)), sa.Column("visit_status", sa.String(40)), sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("event_date", "event_type", "appointment_id", name="uq_analytics_appointment_daily"))
        else:
            op.create_table(table, sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_date", sa.String(10), nullable=False), sa.Column("event_type", sa.String(80), nullable=False), sa.Column("service_id", sa.Integer(), nullable=False), sa.Column("department_id", sa.Integer()), sa.Column("status", sa.String(40)), sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("event_date", "event_type", "service_id", name="uq_analytics_service_daily"))


def downgrade() -> None:
    op.drop_table("analytics_services_daily")
    op.drop_table("analytics_appointments_daily")
    op.drop_table("analytics_processed_events")
    op.drop_column("content_chunks", "token_count")
    op.drop_column("content_chunks", "source_id")
    op.drop_column("content_chunks", "source_type")
    op.drop_column("appointments", "visit_status")
    op.drop_column("providers", "specialty")
    sa.Enum(name="visitstatus").drop(op.get_bind(), checkfirst=True)