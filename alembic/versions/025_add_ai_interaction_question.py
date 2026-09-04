from alembic import op
import sqlalchemy as sa


revision = "025_add_ai_interaction_question"
down_revision = "024_analytics_failed_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ai_interactions")} if "ai_interactions" in inspector.get_table_names() else set()
    if "question" not in columns:
        op.add_column("ai_interactions", sa.Column("question", sa.Text(), nullable=False, server_default=""))
        op.alter_column("ai_interactions", "question", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("ai_interactions")} if "ai_interactions" in inspector.get_table_names() else set()
    if "question" in columns:
        op.drop_column("ai_interactions", "question")
