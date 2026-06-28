"""Shared test configuration.

Tests run without Postgres or Redis: the dedupe logic is pure, the normalize
job uses an in-memory fake session, and the ``/metrics`` endpoint's Redis call
is faked. These defaults keep settings import-safe in CI when no ``.env`` is
present.
"""

from __future__ import annotations

import os

# The API refuses to start without a real (non-placeholder) JWT secret, and
# TestClient runs the lifespan, so set one before any api/shared import.
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-placeholder")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://cms:cms@localhost:5432/cms_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "test-admin-password")
