"""Tiny aiohttp /healthz server for non-HTTP services (bot, worker, userbot).

Checks Postgres + Redis reachability and returns 200 (ok) or 503 (degraded).
Run via `start_health_server(service, port)` which returns the aiohttp task.

Extra checks can be registered via the ``extra_checks`` parameter — a mapping
of ``name -> async callable`` where each callable returns ``(ok: bool, detail: str)``.
Any failing extra check contributes "degraded" and HTTP 503.  Exceptions raised
by a check are caught and treated as ``(False, "error:<ExcType>")``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from aiohttp import web
from sqlalchemy import text

from shared.db import SessionLocal
from shared.logging import get_logger
from shared.tasks import _get_pool

_log = get_logger("health")

# Type alias for an extra-check callable.
ExtraCheck = Callable[[], Awaitable[tuple[bool, str]]]


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

    # Run any registered extra checks (e.g. MTProto liveness for userbot).
    extra: dict[str, ExtraCheck] = request.app.get("extra_checks") or {}
    for name, fn in extra.items():
        try:
            check_ok, detail = await fn()
        except Exception as exc:
            check_ok, detail = False, f"error:{type(exc).__name__}"
        checks[name] = detail if not check_ok else "ok"
        if not check_ok:
            ok = False

    status = 200 if ok else 503
    return web.json_response(
        {"status": "ok" if ok else "degraded", "service": request.app["service"], "checks": checks},
        status=status,
    )


async def _run(service: str, port: int, extra_checks: dict[str, ExtraCheck] | None = None) -> None:
    app = web.Application()
    app["service"] = service
    app["extra_checks"] = extra_checks or {}
    app.router.add_get("/healthz", _healthz)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    _log.info("healthz-listening", service=service, port=port)
    # Block forever (the task is awaited for the lifetime of the service).
    await asyncio.Event().wait()


def start_health_server(
    service: str,
    port: int,
    extra_checks: dict[str, ExtraCheck] | None = None,
) -> asyncio.Task:
    """Start a /healthz aiohttp server and return the background Task.

    Args:
        service: Service name included in the JSON response.
        port: TCP port to listen on.
        extra_checks: Optional mapping of check-name to async callables.
            Each callable must return ``(ok: bool, detail: str)``.
            Any failure sets overall status to ``degraded`` (HTTP 503).
            Existing callers that omit ``extra_checks`` are unaffected.
    """
    return asyncio.create_task(
        _run(service, port, extra_checks),
        name=f"healthz:{service}",
    )
