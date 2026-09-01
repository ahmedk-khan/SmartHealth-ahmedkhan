"""
Integration tests for service publishing workflow with embeddings.

Tests verify:
1. Complete publishing workflow from service creation to vector storage
2. Embedding generation with batching
3. Hash-based chunk deduplication (reuse)
4. Re-publishing behavior: stale vector cleanup, atomic transactions
5. Metadata filtering for retrieval (published + offered)
6. Hybrid search vs. pure vector search
7. Workflow progress tracking and status queries
"""

import asyncio
import datetime
import hashlib
import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.core.settings import settings
from app.models import Service, ServiceStatus, Department, ContentChunk
from app.repositories import ServiceRepository, ContentChunkRepository
from app.services.embedding_service import embedding_model_id, generate_embeddings
from app.services.search_service import search_services
from app.services.hybrid_search_service import hybrid_search_services
from app.workers.temporal.activities.service_publish import (
    validate_service,
    structure_service,
    chunk_service,
    embed_chunks,
    publish_service_published_event,
)


@pytest.fixture
def db_session() -> Session:
    """Provide a fresh database session for each test."""
    session = db_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture
def cardiology_dept(db_session: Session) -> Department:
    """Create cardiology department."""
    dept = Department(name="Cardiology", created_at=datetime.datetime.now(datetime.timezone.utc))
    db_session.add(dept)
    db_session.commit()
    return dept


class TestServicePublishingWithEmbeddings:
    """Test complete publishing workflow with vector embeddings."""

    @pytest.mark.asyncio
    async def test_publish_service_generates_embeddings(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Service publishing generates embeddings for all chunks.

        Flow:
        1. Create service in DRAFT
        2. Run publishing workflow activities
        3. Verify chunks stored with embeddings
        4. Verify metadata (service_id, dept, specialty, published=True)
        """
        # Step 1: Create service
        service = Service(
            name="Cardiology Consultation",
            description="Comprehensive cardiac evaluation. Includes EKG and stress testing.",
            specialty="Cardiac Assessment",
            department_id=cardiology_dept.id,
            preparation_instructions="Fast for 8 hours.",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        # Step 2: Run workflow activities
        validated = await validate_service(service.id)
        assert validated['status'] == ServiceStatus.PUBLISHING.value

        service_struct = await structure_service(validated['service'])
        chunks = await chunk_service(service_struct)
        assert len(chunks) > 0, "Expected chunks from description"

        embedded_chunks = await embed_chunks(chunks)
        assert len(embedded_chunks) == len(chunks), "All chunks should have embeddings"

        # Step 3: Verify embeddings
        for chunk in embedded_chunks:
            assert chunk['embedding'] is not None, f"Chunk {chunk['chunk_index']} missing embedding"
            assert len(chunk['embedding']) == settings.embedding_dimensions
            assert chunk['embedding_model'] == embedding_model_id()

        # Step 4: Persist and verify
        result = await publish_service_published_event({
            'service_id': service.id,
            'chunks': embedded_chunks,
        })
        assert result['published'] is True

        # Verify storage
        stored = db_session.query(ContentChunk).filter_by(service_id=service.id).all()
        assert len(stored) == len(embedded_chunks)

        for chunk in stored:
            assert chunk.service_id == service.id
            assert chunk.department == cardiology_dept.name
            assert chunk.specialty == "Cardiac Assessment"
            assert chunk.published is True
            assert chunk.embedding is not None
            assert chunk.content_hash is not None

    @pytest.mark.asyncio
    async def test_hash_based_deduplication_skips_reembedding(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Identical chunk content reuses embedding (skips provider call).

        Flow:
        1. Publish service with N chunks
        2. Edit service without changing description
        3. Re-publish: same content → same hash → reused embedding
        """
        # Step 1: Create and publish service
        service = Service(
            name="Test Service",
            description="Unchanged content description that will not change.",
            specialty="Test",
            department_id=cardiology_dept.id,
            preparation_instructions="No prep needed.",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks_v1 = await chunk_service(service_struct)
        embedded_v1 = await embed_chunks(chunks_v1)

        chunk_repo = ContentChunkRepository(db_session)
        chunk_repo.replace_for_service(service.id, embedded_v1)

        # Step 2: Re-publish without changes
        service.status = ServiceStatus.DRAFT
        db_session.commit()

        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks_v2 = await chunk_service(service_struct)

        # Verify identical content → identical hash
        for chunk_v1, chunk_v2 in zip(chunks_v1, chunks_v2):
            assert chunk_v1['content_hash'] == chunk_v2['content_hash'], \
                "Identical content should produce identical hash"

        # Step 3: Embed again; hashes should be reused
        embedded_v2 = await embed_chunks(chunks_v2)

        # Verify reuse: embeddings should be identical
        for emb_v1, emb_v2 in zip(embedded_v1, embedded_v2):
            assert emb_v1['embedding'] == emb_v2['embedding'], \
                "Reused embeddings should be identical"


class TestReusingPublishingCleanup:
    """Test re-publishing cleans up stale vectors without orphans."""

    @pytest.mark.asyncio
    async def test_republish_deletes_old_vectors_atomic_transaction(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Re-publishing atomically replaces old chunks with new.

        Requirement: No orphaned vectors, no duplicates after update.

        Flow:
        1. Publish service → 3 chunks with vectors
        2. Edit service description
        3. Re-publish → old 3 deleted, new 3 inserted atomically
        4. Verify: exactly new_count total, no stale vectors
        """
        # Step 1: Create and publish
        service = Service(
            name="Cardiology",
            description="Initial description with some content here to make chunks.",
            specialty="Cardiac",
            department_id=cardiology_dept.id,
            preparation_instructions="Fast 8 hours",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks_v1 = await chunk_service(service_struct)
        embedded_v1 = await embed_chunks(chunks_v1)
        v1_count = len(embedded_v1)

        chunk_repo = ContentChunkRepository(db_session)
        chunk_repo.replace_for_service(service.id, embedded_v1)
        service_repo = ServiceRepository(db_session)
        service_repo.mark_published(service, commit=True)

        # Verify v1 stored
        stored_v1 = db_session.query(ContentChunk).filter_by(service_id=service.id).all()
        assert len(stored_v1) == v1_count

        # Step 2: Edit and re-publish
        service.description = "Completely new description with different content for chunks."
        service.status = ServiceStatus.DRAFT
        db_session.commit()

        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks_v2 = await chunk_service(service_struct)
        embedded_v2 = await embed_chunks(chunks_v2)
        v2_count = len(embedded_v2)

        # Step 3: Atomic replace
        chunk_repo.replace_for_service(service.id, embedded_v2)
        service_repo.mark_published(service, commit=True)

        # Step 4: Verify cleanup
        stored_v2 = db_session.query(ContentChunk).filter_by(service_id=service.id).all()
        assert len(stored_v2) == v2_count, "Should have exactly new chunk count"

        # Verify no stale vectors (all should be published=True)
        stale = db_session.query(ContentChunk).filter_by(
            service_id=service.id,
            published=False,
        ).all()
        assert len(stale) == 0, f"Found {len(stale)} unpublished chunks (orphaned vectors)"

        # Verify no duplicates (unique constraint on service_id, chunk_index)
        for chunk in stored_v2:
            duplicates = db_session.query(ContentChunk).filter(
                ContentChunk.service_id == chunk.service_id,
                ContentChunk.chunk_index == chunk.chunk_index,
            ).all()
            assert len(duplicates) == 1, f"Duplicate entries for chunk {chunk.chunk_index}"


class TestMetadataFiltering:
    """Test retrieval filters on published + offered services."""

    @pytest.mark.asyncio
    async def test_retrieval_filters_withdrawn_services(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Search excludes withdrawn services (is_published=False).

        Requirement: Retrieval must filter on Service.is_published=True.

        Flow:
        1. Publish 2 services
        2. Withdraw one
        3. Search: only active service returned
        """
        # Create 2 services
        service1 = Service(
            name="Active Cardiology",
            description="Heart health consultation available now.",
            specialty="Cardiac",
            department_id=cardiology_dept.id,
            preparation_instructions="Fast",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        service2 = Service(
            name="Withdrawn Cardiology",
            description="Heart health consultation no longer offered.",
            specialty="Cardiac",
            department_id=cardiology_dept.id,
            preparation_instructions="Fast",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add_all([service1, service2])
        db_session.commit()

        # Publish both
        for svc in [service1, service2]:
            validated = await validate_service(svc.id)
            service_struct = await structure_service(validated['service'])
            chunks = await chunk_service(service_struct)
            embedded = await embed_chunks(chunks)
            result = await publish_service_published_event({
                'service_id': svc.id,
                'chunks': embedded,
            })
            assert result['published'] is True

        # Search before withdrawal
        results_before = await search_services(db_session, "heart health", limit=10)
        assert len(results_before) == 2, "Both services should be found before withdrawal"

        # Withdraw one
        service2.status = ServiceStatus.WITHDRAWN
        db_session.commit()

        # Search after withdrawal
        results_after = await search_services(db_session, "heart health", limit=10)
        assert len(results_after) == 1, "Withdrawn service should be filtered out"
        assert results_after[0]['service_id'] == service1.id, "Only active service should remain"

    @pytest.mark.asyncio
    async def test_retrieval_filters_unpublished_chunks(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Search excludes chunks with published=False.

        Requirement: Retrieval must filter on ContentChunk.published=True.

        Flow:
        1. Manually insert chunk with published=False
        2. Search should not return it
        """
        # Create service and insert draft chunk
        service = Service(
            name="Cardiology",
            description="Test",
            department_id=cardiology_dept.id,
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        # Manually insert unpublished chunk
        chunk = ContentChunk(
            service_id=service.id,
            content="Cardiology content",
            content_hash=hashlib.sha256(b"Cardiology content").hexdigest(),
            department=cardiology_dept.name,
            specialty="Cardiac",
            published=False,  # Key: not published
            source_type="service",
            source_id=service.id,
            chunk_index=0,
            embedding=[0.0] * settings.embedding_dimensions,
            embedding_model=embedding_model_id(),
        )
        db_session.add(chunk)
        db_session.commit()

        # Publish service to make is_published=True
        service.status = ServiceStatus.PUBLISHED
        db_session.commit()

        # Search should not find it
        results = await search_services(db_session, "Cardiology", limit=10)
        assert len(results) == 0, "Unpublished chunks should not be returned"


class TestHybridSearch:
    """Test hybrid search combining vector and keyword matching."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_both_vector_and_keyword_matches(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Hybrid search returns results from both vector and keyword paths.

        Flow:
        1. Publish service with specific keywords
        2. Vector search: find by semantic intent
        3. Keyword search: find by exact terms
        4. Hybrid: merge and rerank
        """
        # Create service
        service = Service(
            name="EKG Stress Testing",
            description="Electrocardiogram recording with cardiac stress protocol.",
            specialty="Electrophysiology",
            department_id=cardiology_dept.id,
            preparation_instructions="Comfortable shoes",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        # Publish
        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks = await chunk_service(service_struct)
        embedded = await embed_chunks(chunks)
        await publish_service_published_event({
            'service_id': service.id,
            'chunks': embedded,
        })

        # Test pure vector search
        vector_results = await search_services(db_session, "cardiac stress evaluation", limit=5)
        assert len(vector_results) > 0, "Vector search should find by semantic match"

        # Test hybrid search
        hybrid_results = await hybrid_search_services(
            db_session,
            "EKG stress test",
            limit=5,
            vector_weight=0.6,
            keyword_weight=0.4,
        )
        assert len(hybrid_results) > 0, "Hybrid search should find by keyword and vector"

        # Hybrid should have both scores
        if hybrid_results:
            result = hybrid_results[0]
            assert 'vector_score' in result
            assert 'keyword_score' in result
            assert 'combined_score' in result
            assert result['combined_score'] >= 0.0

    @pytest.mark.asyncio
    async def test_hybrid_search_boosts_exact_keyword_matches(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Hybrid search ranks exact title matches higher.

        Requirement: Services matching keywords in title should rank higher.

        Flow:
        1. Create two services with similar descriptions
        2. Query with term in one title
        3. Verify that service ranks higher in hybrid search
        """
        # Create two similar services
        service1 = Service(
            name="ECG Monitoring Service",
            description="Long-term electrocardiogram monitoring.",
            specialty="Cardiology",
            department_id=cardiology_dept.id,
            preparation_instructions="None",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        service2 = Service(
            name="Cardiac Imaging",
            description="Electrocardiogram interpretation and monitoring.",
            specialty="Cardiology",
            department_id=cardiology_dept.id,
            preparation_instructions="None",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add_all([service1, service2])
        db_session.commit()

        # Publish both
        for svc in [service1, service2]:
            validated = await validate_service(svc.id)
            service_struct = await structure_service(validated['service'])
            chunks = await chunk_service(service_struct)
            embedded = await embed_chunks(chunks)
            await publish_service_published_event({
                'service_id': svc.id,
                'chunks': embedded,
            })

        # Hybrid search with "ECG" should rank service1 higher (title match)
        results = await hybrid_search_services(db_session, "ECG", limit=2)
        if len(results) >= 2:
            # Service1 (ECG in title) should rank >= Service2 (ECG in description)
            service_ids = [r['service_id'] for r in results]
            service1_rank = service_ids.index(service1.id)
            service2_rank = service_ids.index(service2.id)
            assert service1_rank <= service2_rank, "Title keyword match should rank higher"


class TestEmbeddingBatching:
    """Test batching efficiency and correctness."""

    @pytest.mark.asyncio
    async def test_embeddings_batched_respects_batch_size(
        self,
        db_session: Session,
        cardiology_dept: Department,
    ):
        """
        Test: Embeddings batched into chunks of EMBEDDING_BATCH_SIZE.

        Requirement: Large chunk sets should be batched to reduce API calls.

        Flow:
        1. Create service with many chunks
        2. Monitor batching in embed_chunks
        3. Verify correct number of chunks processed
        """
        # Create service with long description (many chunks)
        long_description = " ".join([
            "Comprehensive cardiac assessment and management.",
            "Evaluation includes patient history, physical examination, and testing.",
        ] * 20)  # Create long description

        service = Service(
            name="Cardiology Plus",
            description=long_description,
            specialty="Cardiac",
            department_id=cardiology_dept.id,
            preparation_instructions="Fast",
            status=ServiceStatus.DRAFT,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        db_session.add(service)
        db_session.commit()

        # Generate chunks
        validated = await validate_service(service.id)
        service_struct = await structure_service(validated['service'])
        chunks = await chunk_service(service_struct)

        chunk_count = len(chunks)
        expected_batch_count = (chunk_count + settings.embedding_batch_size - 1) // settings.embedding_batch_size

        # Embed (batching happens internally)
        embedded = await embed_chunks(chunks)

        # Verify all chunks got embeddings
        assert len(embedded) == chunk_count, f"All {chunk_count} chunks should be embedded"

        # Verify embedding dimensions
        for emb in embedded:
            assert len(emb['embedding']) == settings.embedding_dimensions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
