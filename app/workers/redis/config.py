"""Redis connection configuration and key namespace conventions."""

from app.core.settings import settings

REDIS_URL = settings.redis_url
KEY_PREFIX = "smarthealth"
SLOT_CACHE_TTL_SECONDS = 60


def build_key(*parts: object) -> str:
    return ":".join([KEY_PREFIX, *(str(part) for part in parts)])
