from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.settings import settings


engine = create_engine(settings.database_url, future=True) # engine => the connector btw the orm and databse
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(bind=engine)
        return

    inspector = inspect(engine)
    try:
        column_names = {column["name"] for column in inspector.get_columns("services")}
    except Exception:
        return

    if "status" in column_names:
        return

    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            enum_exists = connection.execute(
                text("SELECT 1 FROM pg_type WHERE typname = 'servicestatus'")
            ).scalar_one_or_none()
            if enum_exists is None:
                connection.execute(
                    text(
                        "CREATE TYPE servicestatus AS ENUM ('DRAFT', 'PUBLISHING', 'PUBLISHED', 'UNPUBLISHING', 'UNPUBLISHED')"
                    )
                )

            connection.execute(
                text(
                    "ALTER TABLE services ADD COLUMN status servicestatus NOT NULL DEFAULT 'DRAFT'"
                )
            )
            connection.execute(
                text(
                    "UPDATE services SET status = CASE WHEN is_published THEN 'PUBLISHED'::servicestatus ELSE 'DRAFT'::servicestatus END"
                )
            )
            connection.execute(text("ALTER TABLE services ALTER COLUMN status DROP DEFAULT"))
        else:
            connection.execute(
                text("ALTER TABLE services ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'DRAFT'")
            )
            connection.execute(
                text(
                    "UPDATE services SET status = CASE WHEN is_published THEN 'PUBLISHED' ELSE 'DRAFT' END"
                )
            )
            connection.execute(text("ALTER TABLE services ALTER COLUMN status DROP DEFAULT"))
