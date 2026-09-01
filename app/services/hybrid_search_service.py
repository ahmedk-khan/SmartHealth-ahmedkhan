"""
Hybrid search service combining vector similarity and keyword (BM25) matching.

This service improves retrieval accuracy by:
1. Running parallel vector search (semantic understanding)
2. Running parallel keyword search (exact term matching)
3. Merging and reranking results
4. Documenting confidence factors for client applications

Usage:
    results = await hybrid_search_services(db, query, limit=5)
    # Returns ranked list with both vector_score and keyword_score
"""

import logging
import math
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.exceptions import app_error
from app.core.settings import settings
from app.models import ContentChunk, Service
from app.repositories import ContentChunkRepository
from app.services.embedding_service import generate_embeddings

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Combines vector and keyword search for improved retrieval."""

    def __init__(self, db: Session):
        self.db = db
        self.chunk_repo = ContentChunkRepository(db)

    async def search(
        self,
        query: str,
        limit: int = 5,
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
        min_similarity: Optional[float] = None,
    ) -> list[dict]:
        """
        Execute hybrid search combining vector and keyword scores.

        Args:
            query: User's search query
            limit: Maximum number of results
            vector_weight: Weight for vector similarity (0.0-1.0)
            keyword_weight: Weight for keyword match (0.0-1.0)
            min_similarity: Minimum combined score to include result (default: settings.RETRIEVAL_MIN_SIMILARITY)

        Returns:
            List of ranked results with metadata:
            - service_id, service_name
            - vector_score: semantic similarity (0.0-1.0)
            - keyword_score: BM25-like relevance (0.0-1.0)
            - combined_score: weighted combination
            - match_type: "vector_only", "keyword_only", or "hybrid"
            - department, specialty, content
        """
        if not query or not query.strip():
            return []

        min_sim = min_similarity or settings.retrieval_min_similarity
        norm_weight = vector_weight + keyword_weight
        if norm_weight <= 0:
            raise app_error(
                "Invalid search weights: sum must be > 0",
                status_code=400,
                error_type="invalid_search_weights",
            )

        # Normalize weights to sum to 1.0
        v_weight = vector_weight / norm_weight
        k_weight = keyword_weight / norm_weight

        # Part A: Vector search
        vector_results = await self._vector_search(query, limit * 2)
        vector_by_service = {r['service_id']: r for r in vector_results}

        # Part B: Keyword search
        keyword_results = self._keyword_search(query, limit * 2)
        keyword_by_service = {r['service_id']: r for r in keyword_results}

        # Part C: Merge and rank
        merged: dict[int, dict] = {}

        # Add vector results
        for service_id, result in vector_by_service.items():
            merged[service_id] = {
                'service_id': service_id,
                'service_name': result['service_name'],
                'department': result['department'],
                'specialty': result['specialty'],
                'content': result['content'],
                'vector_score': result['score'],
                'keyword_score': 0.0,
                'match_type': 'vector_only',
            }

        # Add/merge keyword results
        for service_id, result in keyword_by_service.items():
            if service_id in merged:
                merged[service_id]['keyword_score'] = result['score']
                merged[service_id]['match_type'] = 'hybrid'
            else:
                merged[service_id] = {
                    'service_id': service_id,
                    'service_name': result['service_name'],
                    'department': result['department'],
                    'specialty': result['specialty'],
                    'content': result['content'],
                    'vector_score': 0.0,
                    'keyword_score': result['score'],
                    'match_type': 'keyword_only',
                }

        # Compute combined scores
        for result in merged.values():
            result['combined_score'] = (
                result['vector_score'] * v_weight +
                result['keyword_score'] * k_weight
            )

        # Filter by threshold and rank
        ranked = sorted(
            [r for r in merged.values() if r['combined_score'] >= min_sim],
            key=lambda x: (
                x['match_type'] == 'hybrid',  # Hybrid matches rank highest
                x['combined_score'],          # Then by combined score
            ),
            reverse=True,
        )

        return ranked[:limit]

    async def _vector_search(self, query: str, limit: int) -> list[dict]:
        """Execute vector similarity search."""
        try:
            query_embedding = (await generate_embeddings([query]))[0]
        except Exception as exc:
            logger.exception("Failed to generate query embedding", extra={"query": query})
            raise app_error(
                "Search embedding generation failed",
                status_code=503,
                error_type="embedding_generation_failed",
            ) from exc

        try:
            candidates = self.chunk_repo.search_candidates(query_embedding, limit)
        except Exception as exc:
            logger.exception("Vector search failed", extra={"query": query})
            raise app_error(
                "Vector search is temporarily unavailable",
                status_code=503,
                error_type="search_unavailable",
            ) from exc

        results = []
        for chunk, service, score in candidates:
            if score >= settings.retrieval_min_similarity:
                results.append({
                    'service_id': service.id,
                    'service_name': service.name,
                    'score': round(score, 4),
                    'department': chunk.department,
                    'specialty': chunk.specialty,
                    'content': chunk.content,
                })

        return results

    def _keyword_search(self, query: str, limit: int) -> list[dict]:
        """
        Execute keyword search using simple term matching with scoring.

        Scoring logic:
        - Title contains term: +0.3 per term
        - Description contains term: +0.1 per term
        - Department contains term: +0.15 per term
        """
        query_terms = set(word.lower() for word in query.split() if len(word) > 2)
        if not query_terms:
            return []

        # Query all published services
        services = self.db.query(Service, ContentChunk).join(
            ContentChunk,
            Service.id == ContentChunk.service_id,
        ).filter(
            Service.is_published.is_(True),
            ContentChunk.published.is_(True),
        ).all()

        scored: dict[int, dict] = {}

        for service, chunk in services:
            service_id = service.id

            if service_id not in scored:
                scored[service_id] = {
                    'service_id': service_id,
                    'service_name': service.name,
                    'department': chunk.department,
                    'specialty': chunk.specialty,
                    'content': chunk.content,
                    'score': 0.0,
                }

            result = scored[service_id]
            title_lower = service.name.lower()
            desc_lower = service.description.lower() if service.description else ""
            dept_lower = chunk.department.lower() if chunk.department else ""

            # Title matches
            for term in query_terms:
                if term in title_lower:
                    result['score'] += 0.3

            # Description matches
            for term in query_terms:
                if term in desc_lower:
                    result['score'] += 0.1

            # Department matches
            for term in query_terms:
                if term in dept_lower:
                    result['score'] += 0.15

            # Normalize to 0-1 range
            result['score'] = min(1.0, result['score'])

        # Filter and rank
        ranked = sorted(
            [r for r in scored.values() if r['score'] > 0],
            key=lambda x: x['score'],
            reverse=True,
        )

        return ranked[:limit]


async def hybrid_search_services(
    db: Session,
    query: str,
    limit: int = 5,
    vector_weight: float = 0.6,
    keyword_weight: float = 0.4,
) -> list[dict]:
    """
    Convenience function for hybrid search.

    Returns ranked services with combined vector + keyword scores.
    """
    service = HybridSearchService(db)
    return await service.search(
        query,
        limit=limit,
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
    )
