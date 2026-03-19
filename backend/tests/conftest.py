"""
Pytest configuration and shared fixtures.

Sets up test environment variables BEFORE any application code imports,
so that pydantic-settings and encryption modules initialise correctly.
"""

import os

from cryptography.fernet import Fernet

# Generate a valid Fernet key for tests.
# This MUST happen before importing any app module (config.py, encryption.py)
# because they read env vars at import time.
_test_fernet_key = Fernet.generate_key().decode()

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test")
os.environ.setdefault("SUPABASE_SECRET_KEY", "sb_secret_test")
os.environ.setdefault("TRUELAYER_CLIENT_ID", "test-client-id")
os.environ.setdefault("TRUELAYER_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("TRUELAYER_REDIRECT_URI", "pennyapp://callback")
os.environ.setdefault("TRUELAYER_TOKEN_ENCRYPTION_KEY", _test_fernet_key)
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "true")
