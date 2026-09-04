"""Shared test configuration is kept in integration/test_api.py for backward compatibility."""

import os


os.environ["ASYNC_BOOKING_ENABLED"] = "false"
if os.environ.get("RUN_DOCKER_INTEGRATION") != "1":
	os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./app.db"
os.environ.setdefault("REDIS_URL", "memory://")

# Disable rate limiting for all test cases
from app.core.rate_limit import limiter
limiter.enabled = False
