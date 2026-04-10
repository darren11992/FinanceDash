"""
Shared rate limiter instance.

All routers import `limiter` from here so that configuration
(key function, enabled flag) is consistent across the app.

The limiter is disabled in test mode (APP_ENV=test) to avoid
false 429 responses in the test suite.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.app_env != "test",
)
