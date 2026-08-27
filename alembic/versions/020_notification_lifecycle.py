from alembic import op
import sqlalchemy as sa


revision = "020_notification_lifecycle"
down_revision = "019_analytics_daily_counters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")))
    op.execute("UPDATE notifications SET updated_at = created_at WHERE updated_at IS NULL")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE notificationstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")


def downgrade() -> None:
    op.drop_column("notifications", "updated_at")