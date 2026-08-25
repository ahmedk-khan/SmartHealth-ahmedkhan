from alembic import op
import sqlalchemy as sa


revision = "021_visit_history_fields"
down_revision = "020_notification_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy rows remain nullable; new visit transitions populate all fields.
    pass


def downgrade() -> None:
    pass