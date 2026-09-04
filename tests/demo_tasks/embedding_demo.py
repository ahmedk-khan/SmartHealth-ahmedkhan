"""
Demo: Service Publishing with Embeddings, Re-indexing, and Semantic Search

This module demonstrates:
1. Service publishing with automatic vector embedding generation
2. Hash-based chunk deduplication (skip re-embedding identical content)
3. Re-publishing behavior: old vectors deleted, new vectors inserted
4. Metadata filtering: only published services offered by clinic
5. Semantic search with similarity scoring
6. Hybrid search: vector + keyword ranking
7. Workflow progress tracking
"""

import asyncio
import datetime
import hashlib
import logging
from typing import Any

from sqlalchemy.orm import Session

from app import db as db_module
from app.core.settings import settings
from app.models import Service, ServiceStatus, Department
from app.repositories import ServiceRepository, ContentChunkRepository
from app.services.embedding_service import embedding_model_id, generate_embeddings
from app.services.search_service import search_services

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmbeddingDemoScenario:
    """Demonstrates embedding, re-indexing, and search scenarios."""

    def __init__(self, db: Session):
        self.db = db
        self.service_repo = ServiceRepository(db)
        self.chunk_repo = ContentChunkRepository(db)

    async def scenario_1_initial_publish(self) -> dict[str, Any]:
        """
        Scenario 1: Initial service publishing with embeddings

        Flow:
        1. Create service with description and prep instructions
        2. Simulate ServicePublishWorkflow: chunk → embed → persist
        3. Verify chunks stored with embeddings and metadata
        4. Verify search finds the service
        """
        print("\n" + "=" * 80)
        print("SCENARIO 1: Initial Service Publishing with Embeddings")
        print("=" * 80)

        # Setup: Create department
        dept = self.db.query(Department).filter(Department.name == "Cardiology").first()
        if not dept:
            dept = Department(name="Cardiology", created_at=datetime.datetime.now(datetime.timezone.utc))
            self.db.add(dept)
            self.db.commit()

        # Create service
        service = Service(
            name="Cardiology Consultation",
            description=(
                "Comprehensive heart health evaluation including patient history, "
                "physical examination, EKG interpretation, and treatment planning. "
                "Cardiologists assess risk factors and provide preventive care guidance. "
                "Suitable for new patient evaluations, annual checkups, and symptom investigation."
            ),
            specialty="Cardiac Assessment",
            department_id=dept.id,
            preparation_instructions="Fast for 8 hours. Wear comfortable clothing. Bring insurance card and photo ID.",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        self.db.add(service)
        self.db.commit()
        service_id = service.id

        print(f"\n✓ Created service: {service.name} (ID: {service_id})")

        # Simulate chunking (from activity)
        chunks = self._simulate_chunking(service)
        print(f"✓ Generated {len(chunks)} chunks with metadata context")
        print(f"  Sample chunk content (first 200 chars):")
        print(f"  {chunks[0]['content'][:200]}...")

        # Simulate embedding with batching
        embedded_chunks = await self._simulate_embedding(chunks)
        print(f"✓ Generated embeddings for {len(embedded_chunks)} chunks (batch size: {settings.embedding_batch_size})")
        print(f"  Embedding model: {embedded_chunks[0]['embedding_model']}")
        print(f"  Vector dimensions: {len(embedded_chunks[0]['embedding'])}")

        # Simulate persist (from activity)
        self.chunk_repo.replace_for_service(service_id, embedded_chunks)
        self.service_repo.mark_published(service, commit=True)

        # Verify storage
        stored_chunks = self.db.query(__import__('app.models', fromlist=['ContentChunk']).ContentChunk).filter_by(
            service_id=service_id
        ).all()
        print(f"✓ Persisted {len(stored_chunks)} chunks to database")
        for chunk in stored_chunks:
            print(f"  - Chunk {chunk.chunk_index}: hash={chunk.content_hash[:8]}..., "
                  f"dept={chunk.department}, specialty={chunk.specialty}, published={chunk.published}")

        # Test search
        search_results = await search_services(self.db, "heart health evaluation", limit=5)
        print(f"✓ Search found {len(search_results)} result(s)")
        if search_results:
            result = search_results[0]
            print(f"  Service: {result['service_name']}")
            print(f"  Similarity score: {result['score']}")
            print(f"  Department: {result['department']}, Specialty: {result['specialty']}")

        return {
            "service_id": service_id,
            "chunks_count": len(stored_chunks),
            "embeddings_generated": len(embedded_chunks),
            "search_found": len(search_results) > 0,
        }

    async def scenario_2_republish_with_edit(self, service_id: int) -> dict[str, Any]:
        """
        Scenario 2: Re-publishing after service edit

        Flow:
        1. Edit service: update specialty and description
        2. Re-run publishing workflow
        3. Verify old vectors deleted (no orphaned vectors)
        4. Verify new vectors with new content inserted
        5. Verify search reflects updated service
        """
        print("\n" + "=" * 80)
        print("SCENARIO 2: Re-Publishing After Service Edit (Stale Vector Cleanup)")
        print("=" * 80)

        # Get service
        service = self.service_repo.get_for_publication(service_id)
        if not service:
            print(f"✗ Service {service_id} not found")
            return {"error": "Service not found"}

        # Verify old chunks exist
        old_chunks = self.db.query(__import__('app.models', fromlist=['ContentChunk']).ContentChunk).filter_by(
            service_id=service_id
        ).all()
        old_chunk_hashes = {(c.chunk_index, c.content_hash) for c in old_chunks}
        print(f"\n✓ Before edit: {len(old_chunks)} chunks exist")
        for chunk in old_chunks:
            print(f"  - Chunk {chunk.chunk_index}: hash={chunk.content_hash[:8]}..., published={chunk.published}")

        # Edit service
        service.specialty = "Echocardiography & Imaging"
        service.description = (
            "Advanced cardiac imaging and functional assessment. "
            "Echocardiography (ultrasound) provides real-time visualization of heart structure and function. "
            "Includes stress echo, tissue Doppler, and 3D imaging when clinically indicated. "
            "Cardiothoracic surgeons use these results for surgical planning."
        )
        service.status = ServiceStatus.DRAFT
        self.db.commit()
        print(f"\n✓ Updated service:")
        print(f"  Specialty: {service.specialty}")
        print(f"  Description (first 100 chars): {service.description[:100]}...")

        # Re-run publishing workflow simulation
        service_struct = {
            "service_id": service.id,
            "title": service.name,
            "description": service.description,
            "specialty": service.specialty,
            "preparation_instructions": service.preparation_instructions,
            "department_id": service.department_id,
            "department_name": service.department.name,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        chunks = self._simulate_chunking(service_struct)
        embedded_chunks = await self._simulate_embedding(chunks)

        # Key operation: replace old chunks with new ones
        print(f"\n✓ Replacing chunks (atomic transaction):")
        print(f"  Old: {len(old_chunks)} chunks")
        print(f"  New: {len(embedded_chunks)} chunks")

        self.chunk_repo.replace_for_service(service_id, embedded_chunks)
        self.service_repo.mark_published(service, commit=True)

        # Verify new chunks
        new_chunks = self.db.query(__import__('app.models', fromlist=['ContentChunk']).ContentChunk).filter_by(
            service_id=service_id
        ).all()
        new_chunk_hashes = {(c.chunk_index, c.content_hash) for c in new_chunks}

        print(f"\n✓ After re-publish: {len(new_chunks)} chunks exist")
        for chunk in new_chunks:
            print(f"  - Chunk {chunk.chunk_index}: hash={chunk.content_hash[:8]}..., published={chunk.published}")

        # Verify stale vector cleanup
        stale_count = len(old_chunk_hashes - new_chunk_hashes)
        new_count = len(new_chunk_hashes - old_chunk_hashes)
        reused_count = len(old_chunk_hashes & new_chunk_hashes)

        print(f"\n✓ Vector lifecycle analysis:")
        print(f"  Deleted (stale): {stale_count}")
        print(f"  Reused (hash match): {reused_count}")
        print(f"  Generated (new): {new_count}")
        print(f"  Total new: {len(embedded_chunks)}")

        # Verify no orphaned vectors
        orphaned = self.db.query(__import__('app.models', fromlist=['ContentChunk']).ContentChunk).filter_by(
            service_id=service_id
        ).filter(__import__('app.models', fromlist=['ContentChunk']).ContentChunk.published == False).all()
        if orphaned:
            print(f"✗ WARNING: Found {len(orphaned)} unpublished chunks (orphaned vectors)")
        else:
            print(f"✓ No orphaned vectors: all chunks are published=True")

        # Test search with updated service
        search_results = await search_services(self.db, "echocardiography imaging", limit=5)
        print(f"\n✓ Updated search results: {len(search_results)} result(s)")
        if search_results:
            result = search_results[0]
            print(f"  Service: {result['service_name']}")
            print(f"  Specialty: {result['specialty']}")
            print(f"  Similarity: {result['score']}")

        return {
            "service_id": service_id,
            "old_chunks": len(old_chunks),
            "new_chunks": len(new_chunks),
            "deleted_vectors": stale_count,
            "reused_vectors": reused_count,
            "generated_vectors": new_count,
            "orphaned_vectors": len(orphaned),
            "search_found": len(search_results) > 0,
        }

    async def scenario_3_metadata_filtering(self, service_id: int) -> dict[str, Any]:
        """
        Scenario 3: Metadata filtering - ensure only offered services are retrieved

        Requirement: Retrieval must filter on:
        - published=True (chunk is published)
        - Service.is_published=True (service is offered)

        Tests:
        1. Create second service (Neurology)
        2. Publish both
        3. Mark one as withdrawn
        4. Search: only active services should appear
        """
        print("\n" + "=" * 80)
        print("SCENARIO 3: Metadata Filtering (Published + Offered)")
        print("=" * 80)

        # Create second service
        neuro_dept = self.db.query(Department).filter(Department.name == "Neurology").first()
        if not neuro_dept:
            neuro_dept = Department(name="Neurology", created_at=datetime.datetime.now(datetime.timezone.utc))
            self.db.add(neuro_dept)
            self.db.commit()

        neuro_service = Service(
            name="Neurological Consultation",
            description="Comprehensive neurological evaluation for headaches, dizziness, and neurological disorders.",
            specialty="Neurology",
            department_id=neuro_dept.id,
            preparation_instructions="No special preparation needed.",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        self.db.add(neuro_service)
        self.db.commit()
        neuro_service_id = neuro_service.id

        # Publish neuro service
        neuro_struct = {
            "service_id": neuro_service.id,
            "title": neuro_service.name,
            "description": neuro_service.description,
            "specialty": neuro_service.specialty,
            "preparation_instructions": neuro_service.preparation_instructions,
            "department_id": neuro_service.department_id,
            "department_name": neuro_service.department.name,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        neuro_chunks = self._simulate_chunking(neuro_struct)
        neuro_embedded = await self._simulate_embedding(neuro_chunks)
        self.chunk_repo.replace_for_service(neuro_service_id, neuro_embedded)
        self.service_repo.mark_published(neuro_service, commit=True)

        print(f"\n✓ Published 2 services:")
        print(f"  1. Cardiology Consultation (ID: {service_id})")
        print(f"  2. Neurological Consultation (ID: {neuro_service_id})")

        # Search before withdrawal
        results_before = await search_services(self.db, "consultation health", limit=10)
        print(f"\n✓ Search before withdrawal: {len(results_before)} results")
        for r in results_before:
            print(f"  - {r['service_name']} (specialty: {r['specialty']})")

        # Withdraw neuro service
        neuro_service.status = ServiceStatus.WITHDRAWN
        self.db.commit()
        print(f"\n✓ Withdrew Neurological Consultation")

        # Search after withdrawal
        results_after = await search_services(self.db, "consultation health", limit=10)
        print(f"\n✓ Search after withdrawal: {len(results_after)} results")
        for r in results_after:
            print(f"  - {r['service_name']} (specialty: {r['specialty']})")

        # Verify filtering worked
        neuro_in_results = any(r['service_id'] == neuro_service_id for r in results_after)
        if neuro_in_results:
            print(f"\n✗ FILTER FAILED: Withdrawn service still returned in search")
        else:
            print(f"\n✓ FILTER SUCCESS: Withdrawn service correctly filtered out")

        return {
            "published_services": 2,
            "search_results_before": len(results_before),
            "search_results_after": len(results_after),
            "withdrawn_service_filtered": not neuro_in_results,
        }

    async def scenario_4_hybrid_search_comparison(self, service_id: int) -> dict[str, Any]:
        """
        Scenario 4: Vector vs. Hybrid search comparison

        Demonstrates:
        1. Pure vector search (semantic matching)
        2. Hybrid search (vector + keyword boost)
        3. Comparison of results and scoring
        """
        print("\n" + "=" * 80)
        print("SCENARIO 4: Pure Vector vs. Hybrid Search Comparison")
        print("=" * 80)

        query = "EKG and heart imaging"
        print(f"\nQuery: '{query}'")

        # Pure vector search (current implementation)
        print(f"\n--- Pure Vector Search ---")
        vector_results = await search_services(self.db, query, limit=5)
        print(f"Results: {len(vector_results)}")
        for r in vector_results:
            print(f"  Score: {r['score']:.4f} | {r['service_name']}")
            print(f"    Specialty: {r['specialty']}")

        # Simulate hybrid search
        print(f"\n--- Hybrid Search (Vector + Keyword Boost) ---")
        hybrid_results = self._hybrid_search_simulation(vector_results, query)
        for r in hybrid_results:
            print(f"  Score: {r['hybrid_score']:.4f} | {r['service_name']}")
            print(f"    Vector: {r['vector_score']:.4f}, Keyword boost: {r['keyword_boost']}")

        print(f"\n✓ Comparison:")
        print(f"  Vector search strength: Understands semantic intent")
        print(f"  Hybrid search strength: Combines semantic + exact keyword matching")
        print(f"  Trade-off: Hybrid slightly slower, reduces semantic drift risk")

        return {
            "query": query,
            "vector_results": len(vector_results),
            "hybrid_results": len(hybrid_results),
        }

    def _simulate_chunking(self, service_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Simulate the chunk_service activity."""
        title = service_data.get("title") or service_data.get("name", "Service")
        description = service_data.get("description", "")
        specialty = service_data.get("specialty") or "Not specified"
        department_name = service_data.get("department_name", "Not specified")
        prep = service_data.get("preparation_instructions") or "Not specified"

        # Create labeled context
        context = "\n".join([
            f"Service: {title}",
            f"Department: {department_name}",
            f"Specialty: {specialty}",
            f"Preparation instructions: {prep}",
        ])

        chunks = []
        chunk_size = 120
        for idx in range(0, max(len(description), 1), chunk_size):
            content = f"{context}\n\n{description[idx : idx + chunk_size]}"
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            chunks.append({
                "chunk_index": idx // chunk_size,
                "content": content,
                "content_hash": content_hash,
                "service_id": service_data.get("service_id"),
                "department": department_name,
                "specialty": specialty,
                "published": True,
                "source_type": "service",
                "source_id": service_data.get("service_id"),
            })

        return chunks

    async def _simulate_embedding(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Simulate the embed_chunks activity with batching.

        Shows:
        1. Hash-based reuse checking
        2. Batch API calls
        3. Embedding attribution
        """
        model_id = embedding_model_id()

        # Check for reusable embeddings (hash match)
        reusable = {}
        service_id = chunks[0].get("service_id")
        if service_id is not None:
            chunk_keys = [
                (chunk["chunk_index"], chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode()).hexdigest())
                for chunk in chunks
            ]
            reusable = self.chunk_repo.get_reusable_embeddings(service_id, chunk_keys, model_id)

        # Separate reusable from pending
        pending = []
        for chunk in chunks:
            content_hash = chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode()).hexdigest()
            if not reusable.get((chunk["chunk_index"], content_hash)):
                pending.append(chunk | {"content_hash": content_hash})

        logger.info(f"Embedding: {len(pending)} pending, {len(reusable)} reused")

        # Batch embed
        batch_size = settings.embedding_batch_size
        embedded_by_key = {}
        for start in range(0, len(pending), batch_size):
            batch = pending[start : start + batch_size]
            logger.info(f"  Batch {start // batch_size + 1}: {len(batch)} chunks")
            embeddings = await generate_embeddings([c["content"] for c in batch])
            for chunk, embedding in zip(batch, embeddings):
                key = (chunk["chunk_index"], chunk["content_hash"])
                embedded_by_key[key] = embedding

        # Assemble final
        embedded_chunks = []
        for chunk in chunks:
            content_hash = chunk.get("content_hash") or hashlib.sha256(chunk["content"].encode()).hexdigest()
            key = (chunk["chunk_index"], content_hash)
            embedding = reusable.get(key) or embedded_by_key.get(key)
            if not embedding:
                logger.warning(f"Missing embedding for chunk {chunk['chunk_index']}")
                continue

            embedded_chunks.append(chunk | {
                "content_hash": content_hash,
                "embedding": embedding,
                "embedding_model": model_id,
            })

        return embedded_chunks

    @staticmethod
    def _hybrid_search_simulation(vector_results: list[dict], query: str) -> list[dict]:
        """
        Simulate hybrid search by boosting vector scores for keyword matches.

        In production, this would:
        1. Run BM25 query on service titles/descriptions
        2. Merge results
        3. Rerank by combined score
        """
        hybrid = []
        query_terms = set(query.lower().split())

        for result in vector_results:
            keyword_boost = 0.0
            title_lower = result['service_name'].lower()
            content_lower = result['content'].lower()

            # Simple keyword matching
            for term in query_terms:
                if term in title_lower:
                    keyword_boost += 0.15  # Title match stronger
                elif term in content_lower:
                    keyword_boost += 0.05

            hybrid_score = min(1.0, result['score'] + keyword_boost)
            hybrid.append(result | {
                "hybrid_score": hybrid_score,
                "keyword_boost": keyword_boost,
            })

        return sorted(hybrid, key=lambda x: x['hybrid_score'], reverse=True)


async def run_all_scenarios():
    """Run all embedding demo scenarios."""
    db = db_module.SessionLocal()
    demo = EmbeddingDemoScenario(db)

    try:
        # Scenario 1: Initial publish
        result1 = await demo.scenario_1_initial_publish()
        print(f"\n✓ Scenario 1 complete: {result1}")

        service_id = result1['service_id']

        # Scenario 2: Re-publish with edit
        result2 = await demo.scenario_2_republish_with_edit(service_id)
        print(f"\n✓ Scenario 2 complete: {result2}")

        # Scenario 3: Metadata filtering
        result3 = await demo.scenario_3_metadata_filtering(service_id)
        print(f"\n✓ Scenario 3 complete: {result3}")

        # Scenario 4: Hybrid search
        result4 = await demo.scenario_4_hybrid_search_comparison(service_id)
        print(f"\n✓ Scenario 4 complete: {result4}")

        print("\n" + "=" * 80)
        print("ALL SCENARIOS COMPLETE")
        print("=" * 80)

    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(run_all_scenarios())
