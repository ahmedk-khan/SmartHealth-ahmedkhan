from alembic import op


revision = "018_add_query_indexes"
down_revision = "017_required_domain_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    indexes = (
        ("ix_services_status", "services", ["status"]),
        ("ix_slots_provider_id", "slots", ["provider_id"]),
        ("ix_slots_status", "slots", ["status"]),
        ("ix_appointments_patient_id", "appointments", ["patient_id"]),
        ("ix_appointments_status", "appointments", ["status"]),
        ("ix_content_chunks_source_type", "content_chunks", ["source_type"]),
        ("ix_analytics_daily_date", "analytics_daily", ["date"]),
    )
    for name, table, columns in indexes:
        op.create_index(name, table, columns, unique=False)


def downgrade() -> None:
    for name, table in (
        ("ix_analytics_daily_date", "analytics_daily"),
        ("ix_content_chunks_source_type", "content_chunks"),
        ("ix_appointments_status", "appointments"),
        ("ix_appointments_patient_id", "appointments"),
        ("ix_slots_status", "slots"),
        ("ix_slots_provider_id", "slots"),
        ("ix_services_status", "services"),
    ):
        op.drop_index(name, table_name=table)