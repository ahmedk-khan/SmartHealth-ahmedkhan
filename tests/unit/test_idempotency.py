"""Unit tests for booking idempotency store behavior."""

from unittest.mock import MagicMock

import pytest

from app.core.exceptions import AppError
from app.core.idempotency import IdempotencyStoreUnavailableError, RedisIdempotencyStore


def test_claim_uses_in_memory_fallback_in_test_env(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "app_env", "test")
    store = RedisIdempotencyStore()
    store._redis = None

    assert store.claim(1, "booking-key") is True
    assert store.claim(1, "booking-key") is False


def test_claim_fails_closed_in_production_without_redis(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "app_env", "production")
    store = RedisIdempotencyStore()
    store._redis = None

    with pytest.raises(IdempotencyStoreUnavailableError):
        store.claim(7, "booking-key")


def test_claim_uses_redis_when_available(monkeypatch):
    from app.core.settings import settings

    monkeypatch.setattr(settings, "app_env", "production")
    store = RedisIdempotencyStore()
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    store._redis = mock_redis

    assert store.claim(3, "booking-key") is True
    mock_redis.set.assert_called_once()


def test_idempotency_unavailable_error_is_app_error():
    error = IdempotencyStoreUnavailableError()
    assert isinstance(error, AppError)
    assert error.status_code == 503
