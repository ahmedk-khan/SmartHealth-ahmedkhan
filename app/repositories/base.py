from sqlalchemy.orm import Session


class BaseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def audit(self, entity_type: str, entity_id: int, action: str, *, actor_user_id: int | None = None, before: dict | None = None, after: dict | None = None) -> None:
        from app.models.audit import AuditLog

        self.db.add(AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_user_id=actor_user_id,
            before=before,
            after=after,
        ))