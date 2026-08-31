from app.models import AIInteraction
from app.repositories.base import BaseRepository


class AIInteractionRepository(BaseRepository):
    def create_interaction(self, **values) -> AIInteraction:
        interaction = AIInteraction(**values)
        self.db.add(interaction)
        self.db.commit()
        self.db.refresh(interaction)
        return interaction
