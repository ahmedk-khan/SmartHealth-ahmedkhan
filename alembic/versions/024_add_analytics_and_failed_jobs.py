from alembic import op
import sqlalchemy as sa


revision = "024_analytics_failed_jobs"
down_revision = "023_update_embedding_dimensions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "failed_jobs" not in tables:
        op.create_table(
            "failed_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("task_name", sa.String(255), nullable=False),
            sa.Column("task_id", sa.String(255), nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="FAILED"),
            sa.Column("exception_type", sa.String(255), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("traceback", sa.Text(), nullable=True),
            sa.Column("payload", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_failed_jobs_id", "failed_jobs", ["id"])
        op.create_index("ix_failed_jobs_task_name", "failed_jobs", ["task_name"])
        op.create_index("ix_failed_jobs_task_id", "failed_jobs", ["task_id"])

    if "analytics_processed_events" not in tables:
        op.create_table(
            "analytics_processed_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_id", sa.String(128), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("topic", sa.String(120), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_id"),
        )
        op.create_index("ix_analytics_processed_events_id", "analytics_processed_events", ["id"])
        op.create_index("ix_analytics_processed_events_event_id", "analytics_processed_events", ["event_id"])
        op.create_index("ix_analytics_processed_events_event_type", "analytics_processed_events", ["event_type"])
        op.create_index("ix_analytics_processed_events_topic", "analytics_processed_events", ["topic"])

    if "analytics_appointments_daily" not in tables:
        op.create_table(
            "analytics_appointments_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_date", sa.String(10), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("appointment_id", sa.Integer(), nullable=False),
            sa.Column("patient_id", sa.Integer(), nullable=True),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("service_id", sa.Integer(), nullable=True),
            sa.Column("slot_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("visit_status", sa.String(40), nullable=True),
            sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_date", "event_type", "appointment_id", name="uq_analytics_appointment_daily"),
        )
        for name, column in (
            ("id", "id"),
            ("event_date", "event_date"),
            ("event_type", "event_type"),
            ("appointment_id", "appointment_id"),
            ("patient_id", "patient_id"),
            ("provider_id", "provider_id"),
            ("service_id", "service_id"),
            ("slot_id", "slot_id"),
        ):
            op.create_index(f"ix_analytics_appointments_daily_{name}", "analytics_appointments_daily", [column])

    if "analytics_services_daily" not in tables:
        op.create_table(
            "analytics_services_daily",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("event_date", sa.String(10), nullable=False),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("service_id", sa.Integer(), nullable=False),
            sa.Column("department_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(40), nullable=True),
            sa.Column("total_events", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("event_date", "event_type", "service_id", name="uq_analytics_service_daily"),
        )
        for name, column in (
            ("id", "id"),
            ("event_date", "event_date"),
            ("event_type", "event_type"),
            ("service_id", "service_id"),
            ("department_id", "department_id"),
        ):
            op.create_index(f"ix_analytics_services_daily_{name}", "analytics_services_daily", [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    archives = {
        "failed_jobs": "failed_jobs_archived",
        "analytics_processed_events": "analytics_processed_events_archived",
        "analytics_appointments_daily": "analytics_appointments_daily_archived",
        "analytics_services_daily": "analytics_services_daily_archived",
    }
    for table, archive in archives.items():
        if table not in tables:
            continue
        if archive in tables:
            raise RuntimeError(f"Cannot archive {table}: {archive} already exists")
        op.rename_table(table, archive)
