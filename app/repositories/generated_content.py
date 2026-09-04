from app.models import GeneratedContent
from app.repositories.base import BaseRepository


class GeneratedContentRepository(BaseRepository):
    def create_generated_content(self, **values) -> GeneratedContent:
        content = GeneratedContent(**values)
        self.db.add(content)
        self.db.commit()
        self.db.refresh(content)
        return content
