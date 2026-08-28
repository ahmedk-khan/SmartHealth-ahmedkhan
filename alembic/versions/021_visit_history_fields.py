from alembic import op
import sqlalchemy as sa


revision = "021_visit_history_fields"
down_revision = "020_notification_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Historical compatibility revision: the required visit columns already exist.
    return None


def downgrade() -> None:
    """No-op because upgrade() intentionally made no schema changes."""
    return None