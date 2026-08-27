import math

from app.models import ContentChunk, Service
from app.repositories.base import BaseRepository


class ContentChunkRepository(BaseRepository):
    def get_reusable_embeddings(self, service_id: int, chunk_keys: list[tuple[int, str]], embedding_model: str) -> dict[tuple[int, str], list[float]]:
        if not chunk_keys:
            return {}
        chunk_indexes = [chunk_index for chunk_index, _ in chunk_keys]
        content_hashes = [content_hash for _, content_hash in chunk_keys]
        rows = self.db.query(ContentChunk).filter(
            ContentChunk.service_id == service_id,
            ContentChunk.chunk_index.in_(chunk_indexes),
            ContentChunk.content_hash.in_(content_hashes),
            ContentChunk.embedding.is_not(None),
            ContentChunk.embedding_model == embedding_model,
        ).all()
        requested = set(chunk_keys)
        return {
            (chunk.chunk_index, chunk.content_hash): chunk.embedding
            for chunk in rows
            if (chunk.chunk_index, chunk.content_hash) in requested
        }

    def replace_for_service(self, service_id: int, chunks: list[dict]) -> None:
        self.db.query(ContentChunk).filter(ContentChunk.service_id == service_id).delete()
        self.db.add_all(
            [
                ContentChunk(
                    service_id=service_id,
                    content_hash=chunk.get("content_hash"),
                    department=chunk["department"],
                    specialty=chunk.get("specialty"),
                    published=chunk.get("published", False),
                    source_type=chunk.get("source_type", "service"),
                    source_id=chunk.get("source_id", service_id),
                    chunk_index=chunk["chunk_index"],
                    content=chunk["content"],
                    token_count=chunk.get("token_count", len(chunk["content"].split())),
                    embedding=chunk["embedding"],
                )
                for chunk in chunks
            ]
        )

    def search_candidates(self, query_embedding: list[float], limit: int) -> list[tuple[ContentChunk, Service, float]]:
        query = (
            self.db.query(ContentChunk, Service)
            .join(Service, ContentChunk.service_id == Service.id)
            .filter(
                ContentChunk.published.is_(True),
                Service.is_published.is_(True),
                ContentChunk.embedding.is_not(None),
            )
        )
        if self.db.bind.dialect.name == "postgresql":
            distance = ContentChunk.embedding.cosine_distance(query_embedding)
            rows = query.add_columns(distance.label("distance")).order_by(distance).limit(limit * 3).all()
            return [(chunk, service, 1.0 - float(distance_value)) for chunk, service, distance_value in rows]

        candidates = [
            (chunk, service, self._cosine_similarity(chunk.embedding, query_embedding))
            for chunk, service in query.all()
        ]
        return sorted(candidates, key=lambda candidate: candidate[2], reverse=True)

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        numerator = sum(a * b for a, b in zip(left, right))
        left_magnitude = math.sqrt(sum(value * value for value in left))
        right_magnitude = math.sqrt(sum(value * value for value in right))
        if not left_magnitude or not right_magnitude:
            return 0.0
        return numerator / (left_magnitude * right_magnitude)