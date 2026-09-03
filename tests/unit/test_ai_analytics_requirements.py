from app.models import AIInteraction, User, UserRole
from app.repositories.ai_interactions import AIInteractionRepository
from app.api.v1.endpoints.analytics import get_ai_analytics
from app.db import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def test_ai_analytics_endpoint_uses_object_response_contract():
    assert get_ai_analytics.__annotations__["return"] == dict[str, object]


def test_ai_interaction_summary_handles_missing_table_gracefully():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = Session()
    try:
        summary = AIInteractionRepository(db).summary()
        assert summary["questions_asked"] == 0
        assert summary["interactions_total"] == 0
        assert summary["intent_breakdown"] == {}
        assert summary["booking_conversions"] == 0
    finally:
        db.close()


def test_ai_interaction_summary_includes_correlation_and_breakdown():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(bind=engine)

    db = Session()
    try:
        user = User(email="ai@example.com", hashed_password="hash", role=UserRole.patient)
        db.add(user)
        db.commit()
        db.refresh(user)

        db.add_all([
            AIInteraction(
                user_id=user.id,
                question="sha256:abc",
                intent="navigation",
                retrieved_ids=[1, 2],
                answer="ok",
                input_tokens=120,
                output_tokens=30,
                latency_ms=900,
                refused=False,
                cache_hit=False,
                correlation_id="corr-123",
            ),
            AIInteraction(
                user_id=user.id,
                question="sha256:def",
                intent="preparation",
                retrieved_ids=[3],
                answer="ok",
                input_tokens=200,
                output_tokens=10,
                latency_ms=1200,
                refused=True,
                cache_hit=False,
                correlation_id="corr-456",
            ),
            AIInteraction(
                user_id=user.id,
                question="sha256:ghi",
                intent="staff_generation",
                retrieved_ids=[9],
                answer="ok",
                input_tokens=300,
                output_tokens=20,
                latency_ms=1500,
                refused=False,
                cache_hit=False,
                correlation_id="corr-789",
            ),
        ])
        db.commit()

        summary = AIInteractionRepository(db).summary()

        assert summary["questions_asked"] >= 3
        assert summary["answered_total"] >= 2
        assert summary["refused_total"] >= 1
        assert "navigation" in summary["intent_breakdown"]
        assert "staff_generation" in summary["intent_breakdown"]
        assert "avg_latency_ms" in summary
        assert "p95_latency_ms" in summary
        assert "total_tokens_used" in summary
        assert "estimated_cost_total_usd" in summary
    finally:
        db.close()
