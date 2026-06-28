"""Pure-function unit tests (no DB/redis required)."""

from __future__ import annotations

import os

# Ensure settings load with sane test defaults even if .env is absent.
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://cms:cms@localhost:5432/cms")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
