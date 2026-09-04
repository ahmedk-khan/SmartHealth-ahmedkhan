"""Add ownership and correlation metadata to generated content."""

from alembic import op
import sqlalchemy as sa


revision = "028_add_generated_content_audit"
down_revision = "027_add_ai_question_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "generated_content" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("generated_content")}
    if "initiated_by_user_id" not in columns:
        op.add_column("generated_content", sa.Column("initiated_by_user_id", sa.Integer(), nullable=True))
        op.create_index("ix_generated_content_initiated_by_user_id", "generated_content", ["initiated_by_user_id"])
    if "correlation_id" not in columns:
        op.add_column("generated_content", sa.Column("correlation_id", sa.String(length=255), nullable=True))
        op.create_index("ix_generated_content_correlation_id", "generated_content", ["correlation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if "generated_content" not in sa.inspect(bind).get_table_names():
        return
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("generated_content")}
    for index_name in ("ix_generated_content_correlation_id", "ix_generated_content_initiated_by_user_id"):
        if index_name in indexes:
            op.drop_index(index_name, table_name="generated_content")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("generated_content")}
    for column_name in ("correlation_id", "initiated_by_user_id"):
        if column_name in columns:
            op.drop_column("generated_content", column_name)