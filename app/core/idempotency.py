import json
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - exercised when redis package is absent
    redis = None

from app.core.exceptions import AppError
from app.core.settings import settings


class IdempotencyStoreUnavailableError(AppError):
    """Raised when idempotency cannot be enforced because Redis is unavailable."""

    def __init__(self) -> None:
        super().__init__(
            "Idempotency store is unavailable",
            status_code=503,
            error_type="idempotency_unavailable",
            code="IDEMPOTENCY_UNAVAILABLE",
        )


class RedisIdempotencyStore:
    def __init__(self) -> None:
        self._redis = None
        self._fallback_store: dict[tuple[int, str], dict[str, Any]] = {}
        self._init_client()

    @staticmethod
    def _allow_in_memory_fallback() -> bool:
        return settings.app_env.lower() in {"local", "test", "development", "dev"}

    def _init_client(self) -> None:
        if redis is None:
            return

        redis_url = settings.redis_url.strip()
        if not redis_url or redis_url.startswith("memory://"):
            return

        try:
            self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None

    def _require_redis(self) -> None:
        if self._redis is None and not self._allow_in_memory_fallback():
            raise IdempotencyStoreUnavailableError()

    def _build_key(self, user_id: int, idempotency_key: str) -> str:
        return f"appointments:idempotency:{user_id}:{idempotency_key}"

    def get(self, user_id: int, idempotency_key: str) -> dict[str, Any] | None:
        if self._redis is not None:
            value = self._redis.get(self._build_key(user_id, idempotency_key))
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return None

        if not self._allow_in_memory_fallback():
            return None

        return self._fallback_store.get((user_id, idempotency_key))

    def set(self, user_id: int, idempotency_key: str, value: dict[str, Any], ttl_seconds: int = 86400) -> None:
        if self._redis is not None:
            self._redis.setex(self._build_key(user_id, idempotency_key), ttl_seconds, json.dumps(value))
            return

        if not self._allow_in_memory_fallback():
            raise IdempotencyStoreUnavailableError()

        self._fallback_store[(user_id, idempotency_key)] = value

    def claim(self, user_id: int, idempotency_key: str, ttl_seconds: int = 300) -> bool:
        """Atomically claim a key so concurrent requests cannot run two sagas."""
        key = self._build_key(user_id, idempotency_key)
        if self._redis is not None:
            return bool(self._redis.set(key, json.dumps({"status": "IN_PROGRESS"}), ex=ttl_seconds, nx=True))

        if not self._allow_in_memory_fallback():
            raise IdempotencyStoreUnavailableError()

        store_key = (user_id, idempotency_key)
        if store_key in self._fallback_store:
            return False
        self._fallback_store[store_key] = {"status": "IN_PROGRESS"}
        return True

    def delete(self, user_id: int, idempotency_key: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._build_key(user_id, idempotency_key))
            return

        if self._allow_in_memory_fallback():
            self._fallback_store.pop((user_id, idempotency_key), None)


idempotency_store = RedisIdempotencyStore()
