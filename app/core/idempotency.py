import json
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover - exercised when redis package is absent
    redis = None

from app.core.settings import settings


class RedisIdempotencyStore:
    def __init__(self) -> None:
        self._redis = None
        self._fallback_store: dict[tuple[int, str], dict[str, Any]] = {}
        self._init_client()

    def _init_client(self) -> None:
        if redis is None:
            return

        try:
            self._redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
            self._redis.ping()
        except Exception:
            self._redis = None

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

        return self._fallback_store.get((user_id, idempotency_key))

    def set(self, user_id: int, idempotency_key: str, value: dict[str, Any], ttl_seconds: int = 86400) -> None:
        if self._redis is not None:
            self._redis.setex(self._build_key(user_id, idempotency_key), ttl_seconds, json.dumps(value))
            return

        self._fallback_store[(user_id, idempotency_key)] = value

    def claim(self, user_id: int, idempotency_key: str, ttl_seconds: int = 300) -> bool:
        """Atomically claim a key so concurrent requests cannot run two sagas."""
        key = self._build_key(user_id, idempotency_key)
        if self._redis is not None:
            return bool(self._redis.set(key, json.dumps({"status": "IN_PROGRESS"}), ex=ttl_seconds, nx=True))
        store_key = (user_id, idempotency_key)
        if store_key in self._fallback_store:
            return False
        self._fallback_store[store_key] = {"status": "IN_PROGRESS"}
        return True

    def delete(self, user_id: int, idempotency_key: str) -> None:
        if self._redis is not None:
            self._redis.delete(self._build_key(user_id, idempotency_key))
        self._fallback_store.pop((user_id, idempotency_key), None)


idempotency_store = RedisIdempotencyStore()
