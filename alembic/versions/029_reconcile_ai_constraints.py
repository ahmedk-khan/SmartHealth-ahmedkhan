"""Reconcile AI table constraints with ORM metadata."""

from alembic import op
import sqlalchemy as sa


revision = "029_reconcile_ai_constraints"
down_revision = "028_add_generated_content_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ai_interactions" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("ai_interactions")}
        if "ix_ai_interactions_id" not in indexes:
            op.create_index("ix_ai_interactions_id", "ai_interactions", ["id"])
        if "ix_ai_interactions_user_id" not in indexes:
            op.create_index("ix_ai_interactions_user_id", "ai_interactions", ["user_id"])
        if bind.dialect.name == "postgresql":
            foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("ai_interactions")}
            if "fk_ai_interactions_user_id_users" not in foreign_keys:
                op.create_foreign_key(
                    "fk_ai_interactions_user_id_users",
                    "ai_interactions",
                    "users",
                    ["user_id"],
                    ["id"],
                )
        if bind.dialect.name == "postgresql":
            op.alter_column("ai_interactions", "question", nullable=True)
            op.execute(sa.text("UPDATE ai_interactions SET question = NULL WHERE question = ''"))

    if "generated_content" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("generated_content")}
        if "ix_generated_content_id" not in indexes:
            op.create_index("ix_generated_content_id", "generated_content", ["id"])
        if bind.dialect.name == "postgresql":
            foreign_keys = {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("generated_content")}
            if "fk_generated_content_appointment_id_appointments" not in foreign_keys:
                op.create_foreign_key(
                    "fk_generated_content_appointment_id_appointments",
                    "generated_content",
                    "appointments",
                    ["appointment_id"],
                    ["id"],
                )
            if "fk_generated_content_initiated_by_user_id_users" not in foreign_keys:
                op.create_foreign_key(
                    "fk_generated_content_initiated_by_user_id_users",
                    "generated_content",
                    "users",
                    ["initiated_by_user_id"],
                    ["id"],
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "generated_content" in inspector.get_table_names():
        if bind.dialect.name == "postgresql":
            for name in ("fk_generated_content_initiated_by_user_id_users", "fk_generated_content_appointment_id_appointments"):
                if name in {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("generated_content")}:
                    op.drop_constraint(name, "generated_content", type_="foreignkey")
        if "ix_generated_content_id" in {index["name"] for index in inspector.get_indexes("generated_content")}:
            op.drop_index("ix_generated_content_id", table_name="generated_content")
    if "ai_interactions" in inspector.get_table_names():
        if bind.dialect.name == "postgresql" and "fk_ai_interactions_user_id_users" in {foreign_key["name"] for foreign_key in inspector.get_foreign_keys("ai_interactions")}:
            op.drop_constraint("fk_ai_interactions_user_id_users", "ai_interactions", type_="foreignkey")
        indexes = {index["name"] for index in inspector.get_indexes("ai_interactions")}
        for name in ("ix_ai_interactions_user_id", "ix_ai_interactions_id"):
            if name in indexes:
                op.drop_index(name, table_name="ai_interactions")