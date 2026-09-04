from sqlalchemy import text
from sqlalchemy.engine import Engine


class HealthRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def check_database_connection(self) -> None:
        """Execute the database readiness query and return nothing."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
