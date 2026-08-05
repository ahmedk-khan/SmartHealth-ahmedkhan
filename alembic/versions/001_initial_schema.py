from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.Enum("patient", "provider", "front_desk", "admin", name="userrole"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)

    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "patients",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=140), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "PUBLISHING",
                "PUBLISHED",
                "UNPUBLISHING",
                "UNPUBLISHED",
                name="servicestatus",
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_services_id"), "services", ["id"], unique=False)
    op.create_index(op.f("ix_services_name"), "services", ["name"], unique=False)

    op.create_table(
        "provider_services",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("provider_id", "service_id"),
    )

    op.create_table(
        "content_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "chunk_index", name="uq_content_chunk_service_index"),
    )

    op.create_table(
        "slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Enum("AVAILABLE", "RESERVED", "BOOKED", "BLOCKED", name="slotstatus"), nullable=False),
        sa.Column("start_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_datetime", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_slots_id"), "slots", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_slots_id"), table_name="slots")
    op.drop_table("slots")
    op.drop_table("provider_services")
    op.drop_index(op.f("ix_services_name"), table_name="services")
    op.drop_index(op.f("ix_services_id"), table_name="services")
    op.drop_table("services")
    op.drop_table("providers")
    op.drop_table("patients")
    op.drop_table("departments")
    op.drop_index(op.f("ix_users_id"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
