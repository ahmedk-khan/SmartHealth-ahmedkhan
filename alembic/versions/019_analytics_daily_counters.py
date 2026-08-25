from alembic import op
import sqlalchemy as sa


revision = "019_analytics_daily_counters"
down_revision = "018_add_query_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("analytics_daily")}
    for name in ("total_patients", "failed_workflows", "wait_samples"):
        if name not in existing:
            op.add_column("analytics_daily", sa.Column(name, sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("analytics_daily", "wait_samples")
    op.drop_column("analytics_daily", "failed_workflows")
    op.drop_column("analytics_daily", "total_patients")