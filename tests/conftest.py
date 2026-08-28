"""Shared test configuration is kept in integration/test_api.py for backward compatibility."""

import os


os.environ["ASYNC_BOOKING_ENABLED"] = "false"
os.environ["REDIS_URL"] = "redis://127.0.0.1:63999/0"
