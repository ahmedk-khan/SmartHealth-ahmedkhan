"""Shared test configuration is kept in integration/test_api.py for backward compatibility."""

import os


os.environ["ASYNC_BOOKING_ENABLED"] = "false"
os.environ.setdefault("REDIS_URL", "memory://")

# Disable rate limiting for all test cases
from app.core.rate_limit import limiter
limiter.enabled = False
