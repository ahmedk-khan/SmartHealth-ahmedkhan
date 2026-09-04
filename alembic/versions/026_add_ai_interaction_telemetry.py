"""Add traceability and feedback fields to AI interactions."""

from alembic import op
import sqlalchemy as sa


revision = "026_add_ai_interaction_telemetry"
down_revision = "025_add_ai_interaction_question"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "ai_interactions" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("ai_interactions")}
    if "conversation_id" not in columns:
        op.add_column("ai_interactions", sa.Column("conversation_id", sa.UUID(), nullable=True))
    if "correlation_id" not in columns:
        op.add_column("ai_interactions", sa.Column("correlation_id", sa.String(length=255), nullable=True))
    if "cache_hit" not in columns:
        op.add_column("ai_interactions", sa.Column("cache_hit", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "answer_quality" not in columns:
        op.add_column("ai_interactions", sa.Column("answer_quality", sa.String(length=32), nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("ai_interactions")}
    if "ix_ai_interactions_conversation_id" not in indexes:
        op.create_index("ix_ai_interactions_conversation_id", "ai_interactions", ["conversation_id"])
    if "ix_ai_interactions_correlation_id" not in indexes:
        op.create_index("ix_ai_interactions_correlation_id", "ai_interactions", ["correlation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ai_interactions" not in inspector.get_table_names():
        return

    indexes = {index["name"] for index in inspector.get_indexes("ai_interactions")}
    if "ix_ai_interactions_correlation_id" in indexes:
        op.drop_index("ix_ai_interactions_correlation_id", table_name="ai_interactions")
    if "ix_ai_interactions_conversation_id" in indexes:
        op.drop_index("ix_ai_interactions_conversation_id", table_name="ai_interactions")

    columns = {column["name"] for column in inspector.get_columns("ai_interactions")}
    for column_name in ("answer_quality", "cache_hit", "correlation_id", "conversation_id"):
        if column_name in columns:
            op.drop_column("ai_interactions", column_name)