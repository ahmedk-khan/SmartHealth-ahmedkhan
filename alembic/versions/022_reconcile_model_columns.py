from alembic import op
import sqlalchemy as sa


revision = "022_reconcile_model_columns"
down_revision = "021_visit_history_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    additions = {
        "users": {
            "full_name": sa.Column("full_name", sa.String(255), nullable=True),
            "is_active": sa.Column("is_active", sa.Boolean(), nullable=True),
        },
        "patients": {
            "dob": sa.Column("dob", sa.Date(), nullable=True),
            "contact": sa.Column("contact", sa.JSON(), nullable=True),
        },
        "departments": {
            "clinic": sa.Column("clinic", sa.String(120), nullable=True),
            "order_index": sa.Column("order_index", sa.Integer(), nullable=True),
        },
        "services": {
            "published_at": sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        },
        "appointments": {
            "booking_key": sa.Column("booking_key", sa.String(255), nullable=True),
            "booked_at": sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        },
        "billings": {
            "idempotency_key": sa.Column("idempotency_key", sa.String(255), nullable=True),
        },
        "waitlist_entries": {
            "provider_id": sa.Column("provider_id", sa.Integer(), nullable=True),
        },
        "content_chunks": {
            "embedded_at": sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
            "embedding_model": sa.Column("embedding_model", sa.String(255), nullable=True),
        },
        "outbox_events": {
            "event_id": sa.Column("event_id", sa.String(128), nullable=True),
            "correlation_id": sa.Column("correlation_id", sa.String(128), nullable=True),
            "published_at": sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        },
        "notifications": {
            "updated_at": sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        },
        "analytics_daily": {
            "total_patients": sa.Column("total_patients", sa.Integer(), nullable=True),
            "failed_workflows": sa.Column("failed_workflows", sa.Integer(), nullable=True),
            "wait_samples": sa.Column("wait_samples", sa.Integer(), nullable=True),
        },
    }
    for table, columns in additions.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, column in columns.items():
            if name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    removals = {
        "users": {"full_name", "is_active"},
        "patients": {"dob", "contact"},
        "departments": {"clinic", "order_index"},
        "services": {"published_at"},
        "appointments": {"booking_key", "booked_at"},
        "billings": {"idempotency_key"},
        "waitlist_entries": {"provider_id"},
        "content_chunks": {"embedded_at", "embedding_model"},
        "outbox_events": {"event_id", "correlation_id", "published_at"},
        "notifications": {"updated_at"},
        "analytics_daily": {"total_patients", "failed_workflows", "wait_samples"},
    }
    for table, columns in removals.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name in columns & existing:
            op.drop_column(table, name)
