from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "017_required_domain_models"
down_revision = "016_add_booking_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    additions = {
        "users": [
            sa.Column("full_name", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
        ],
        "patients": [
            sa.Column("dob", sa.Date(), nullable=True),
            sa.Column("contact", sa.JSON(), nullable=True),
        ],
        "departments": [
            sa.Column("clinic", sa.String(120), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=True),
        ],
        "services": [sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)],
        "appointments": [
            sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        ],
        "appointment_status_history": [
            sa.Column("from_status", sa.String(40), nullable=True),
            sa.Column("to_status", sa.String(40), nullable=True),
            sa.Column("actor", sa.String(255), nullable=True),
            sa.Column("reason", sa.String(500), nullable=True),
        ],
        "billings": [sa.Column("idempotency_key", sa.String(255), nullable=True)],
        "waitlist_entries": [sa.Column("provider_id", sa.Integer(), nullable=True)],
        "content_chunks": [
            sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("embedding_model", sa.String(255), nullable=True),
        ],
        "outbox_events": [
            sa.Column("event_id", sa.String(128), nullable=True),
            sa.Column("correlation_id", sa.String(128), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        ],
    }
    for table, columns in additions.items():
        for column in columns:
            op.add_column(table, column)
    op.create_index("ix_billings_idempotency_key", "billings", ["idempotency_key"], unique=True)
    op.create_index("ix_waitlist_entries_provider_id", "waitlist_entries", ["provider_id"], unique=False)
    op.create_index("ix_outbox_events_event_id", "outbox_events", ["event_id"], unique=True)

    op.create_table(
        "slot_reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False),
        sa.Column("slot_id", sa.Integer(), sa.ForeignKey("slots.id"), nullable=False),
        sa.Column("status", sa.Enum("RESERVED", "RELEASED", "COMMITTED", name="slotreservationstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("appointment_id", sa.Integer(), sa.ForeignKey("appointments.id"), nullable=False, unique=True),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", postgresql.ENUM("NOT_STARTED", "CHECKED_IN", "IN_PROGRESS", "COMPLETED", name="visitstatus", create_type=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "SENT", "FAILED", name="notificationstatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("endpoint", sa.String(255), nullable=False),
        sa.Column("response", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", "user_id", "endpoint", name="uq_idempotency_key_scope"),
    )
    op.create_table(
        "ai_interactions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(120), nullable=False), sa.Column("retrieved_ids", sa.JSON(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True), sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=True), sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True), sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("refused", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "generated_content",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("appointment_id", sa.Integer(), nullable=True),
        sa.Column("report_scope", sa.String(255), nullable=True), sa.Column("type", sa.String(100), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False), sa.Column("model", sa.String(255), nullable=True),
        sa.Column("prompt_version", sa.String(80), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "processed_events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("consumer", sa.String(128), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_id", "consumer", name="uq_processed_event_consumer"),
    )
    op.create_table(
        "analytics_daily",
        sa.Column("date", sa.Date(), primary_key=True), sa.Column("appointments_booked", sa.Integer(), nullable=False),
        sa.Column("completed_visits", sa.Integer(), nullable=False), sa.Column("cancellations", sa.Integer(), nullable=False),
        sa.Column("avg_wait_seconds", sa.Integer(), nullable=True), sa.Column("total_patients", sa.Integer(), nullable=False),
        sa.Column("failed_workflows", sa.Integer(), nullable=False), sa.Column("wait_samples", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in ("analytics_daily", "processed_events", "generated_content", "ai_interactions", "idempotency_keys", "notifications", "visits", "slot_reservations"):
        op.drop_table(table)
    op.drop_index("ix_outbox_events_event_id", table_name="outbox_events")
    op.drop_index("ix_waitlist_entries_provider_id", table_name="waitlist_entries")
    op.drop_index("ix_billings_idempotency_key", table_name="billings")
    for table, columns in {
        "outbox_events": ("published_at", "correlation_id", "event_id"),
        "content_chunks": ("embedding_model", "embedded_at"),
        "waitlist_entries": ("provider_id",),
        "billings": ("idempotency_key",),
        "appointment_status_history": ("reason", "actor", "to_status", "from_status"),
        "appointments": ("booked_at",),
        "services": ("published_at",),
        "departments": ("order_index", "clinic"),
        "patients": ("contact", "dob"),
        "users": ("is_active", "full_name"),
    }.items():
        for column in columns:
            op.drop_column(table, column)