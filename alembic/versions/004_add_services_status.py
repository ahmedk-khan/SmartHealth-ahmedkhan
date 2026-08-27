from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004_add_services_status"
down_revision = "003_add_billings"
branch_labels = None
depends_on = None


service_status_enum = sa.Enum(
    "DRAFT",
    "PUBLISHING",
    "PUBLISHED",
    "UNPUBLISHING",
    "UNPUBLISHED",
    name="servicestatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("services")}

    if "status" not in columns:
        service_status_enum.create(bind, checkfirst=True)
        op.add_column(
            "services",
            sa.Column(
                "status",
                service_status_enum,
                nullable=False,
                server_default=sa.text("'DRAFT'::servicestatus"),
            ),
        )
        op.execute(
            "UPDATE services SET status = CASE WHEN is_published THEN 'PUBLISHED'::servicestatus ELSE 'DRAFT'::servicestatus END"
        )
        op.alter_column("services", "status", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("services")}

    if "status" in columns:
        op.drop_column("services", "status")