"""FastAPI application factory + wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.auth import router as auth_router
from api.limiter import limiter
from api.routers import (
    admins_router,
    audit_router,
    queue_router,
    source_channels_router,
    tags_router,
    templates_router,
)
from api.schemas import HealthOut
from shared.config import get_settings
from shared.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging("api")
    log = get_logger("api")
    settings = get_settings()
    # Fail fast on an unset/placeholder JWT secret (forgeable-token guard).
    settings.require_auth_secret()
    log.info("startup", destination_channel=settings.destination_channel_id)
    yield
    log.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Telegram CMS Bot — Back-office API",
        version="0.1.0",
        lifespan=lifespan,
        root_path="/api",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url=None,
    )

    # Never combine a wildcard origin with credentialed CORS — browsers block it.
    # With an explicit allow-list we enable credentials so the httpOnly refresh
    # cookie is sent cross-origin during development (e.g. localhost:3000 → :8000).
    origins = settings.cors_origin_list
    allow_credentials = "*" not in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "Cookie"],
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(auth_router)
    app.include_router(tags_router)
    app.include_router(templates_router)
    app.include_router(source_channels_router)
    app.include_router(admins_router)
    app.include_router(queue_router)
    app.include_router(audit_router)

    @app.get("/healthz", response_model=HealthOut, tags=["health"])
    async def healthz() -> HealthOut:
        return HealthOut(service="api")

    return app


app = create_app()
