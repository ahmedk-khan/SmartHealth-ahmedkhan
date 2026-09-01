"""Async Redis controls for AI endpoints.

Redis is an optimization and protection dependency for AI requests. If it is
unavailable, AI remains available and booking is unaffected.
"""

import json
import logging
from typing import Any

from app.core.settings import settings

try:
    from redis.asyncio import Redis
except ImportError:  # pragma: no cover
    Redis = None


logger = logging.getLogger(__name__)


class AIRedisStore:
    def __init__(self) -> None:
        self._client = None
        self._task_owners: dict[str, int] = {}

    def _get_client(self):
        if self._client is None and Redis is not None:
            redis_url = settings.redis_url.strip()
            if redis_url and "://" not in redis_url:
                redis_url = f"redis://{redis_url}"
            self._client = Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
        return self._client

    async def allow_request(self, user_id: int) -> bool:
        client = self._get_client()
        if client is None:
            return True
        key = f"smarthealth:ai:rate:{user_id}"
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
            return count <= settings.ai_rate_limit_per_minute
        except Exception:
            logger.warning("AI Redis rate limiter unavailable; allowing request", exc_info=True)
            return True

    async def get_cached_answer(
        self,
        question: str,
        *,
        user_scope: str,
        model_id: str,
        prompt_version: str,
    ) -> dict[str, Any] | None:
        client = self._get_client()
        if client is None:
            return None
        try:
            value = await client.get(self._cache_key(question, user_scope, model_id, prompt_version))
            return json.loads(value) if value else None
        except Exception:
            logger.warning("AI Redis cache unavailable; bypassing cache", exc_info=True)
            return None

    async def cache_answer(
        self,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        *,
        user_scope: str,
        model_id: str,
        prompt_version: str,
    ) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            await client.setex(
                self._cache_key(question, user_scope, model_id, prompt_version),
                settings.ai_cache_ttl_seconds,
                json.dumps({"answer": answer, "citations": citations}),
            )
        except Exception:
            logger.warning("AI Redis cache write failed", exc_info=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def set_task_owner(self, task_id: str, user_id: int, ttl_seconds: int = 86400) -> None:
        """Associate a queued task with its requester for polling authorization."""
        client = self._get_client()
        key = f"smarthealth:task-owner:{task_id}"
        try:
            if client is not None:
                await client.setex(key, ttl_seconds, str(user_id))
            else:
                self._task_owners[task_id] = user_id
        except Exception:
            logger.warning("Task ownership store unavailable; using process-local ownership", exc_info=True)
            self._task_owners[task_id] = user_id

    async def get_task_owner(self, task_id: str) -> int | None:
        client = self._get_client()
        key = f"smarthealth:task-owner:{task_id}"
        try:
            value = await client.get(key) if client is not None else self._task_owners.get(task_id)
            return int(value) if value is not None else None
        except Exception:
            logger.warning("Task ownership lookup unavailable", exc_info=True)
            return self._task_owners.get(task_id)

    @staticmethod
    def _cache_key(question: str, user_scope: str, model_id: str, prompt_version: str) -> str:
        import hashlib

        cache_material = "\x1f".join((question, user_scope, model_id, prompt_version))
        digest = hashlib.sha256(cache_material.encode("utf-8")).hexdigest()
        return f"smarthealth:ai:answer:{digest}"


ai_redis_store = AIRedisStore()
