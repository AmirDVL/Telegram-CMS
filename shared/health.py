"""Tiny aiohttp /healthz server for non-HTTP services (bot, worker, userbot).

Checks Postgres + Redis reachability and returns 200 (ok) or 503 (degraded).
Run via `start_health_server(service, port)` which returns the aiohttp task.
"""

from __future__ import annotations

import asyncio

from aiohttp import web
from sqlalchemy import text

from shared.db import SessionLocal
from shared.logging import get_logger
from shared.tasks import _get_pool

_log = get_logger("health")


async def _healthz(request: web.Request) -> web.Response:
    checks: dict[str, str] = {}
    ok = True

    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error:{type(e).__name__}"
        ok = False

    try:
        redis = await _get_pool()
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error:{type(e).__name__}"
        ok = False

    status = 200 if ok else 503
    return web.json_response(
        {"status": "ok" if ok else "degraded", "service": request.app["service"], "checks": checks},
        status=status,
    )


async def _run(service: str, port: int) -> None:
    app = web.Application()
    app["service"] = service
    app.router.add_get("/healthz", _healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    _log.info("healthz-listening", service=service, port=port)
    # Block forever (the task is awaited for the lifetime of the service).
    await asyncio.Event().wait()


def start_health_server(service: str, port: int) -> asyncio.Task:
    return asyncio.create_task(_run(service, port), name=f"healthz:{service}")
