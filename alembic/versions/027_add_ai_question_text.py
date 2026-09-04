"""Store conversation text separately from the audit hash."""

from alembic import op
import sqlalchemy as sa


revision = "027_add_ai_question_text"
down_revision = "026_add_ai_interaction_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "ai_interactions" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ai_interactions")}
    if "question_text" not in columns:
        op.add_column("ai_interactions", sa.Column("question_text", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "ai_interactions" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("ai_interactions")}
    if "question_text" in columns:
        op.drop_column("ai_interactions", "question_text")