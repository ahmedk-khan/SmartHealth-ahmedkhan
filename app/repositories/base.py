from sqlalchemy.orm import Session


class BaseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(self, entity) -> None:
        self.db.add(entity)

    def flush(self) -> None:
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, entity) -> None:
        self.db.refresh(entity)

    def rollback(self) -> None:
        self.db.rollback()

    def save(self, entity) -> None:
        self.db.add(entity)
        self.db.commit()

    def save_and_refresh(self, entity) -> None:
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)

    def delete(self, entity) -> None:
        self.db.delete(entity)
        self.db.commit()

    def audit(self, entity_type: str, entity_id: int, action: str, *, actor_user_id: int | None = None, before: dict | None = None, after: dict | None = None) -> None:
        from app.models.audit import AuditLog

        self.db.add(
            AuditLog(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                actor_user_id=actor_user_id,
                before=before,
                after=after,
            )
        )
