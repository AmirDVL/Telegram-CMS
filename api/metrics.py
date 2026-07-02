"""Prometheus metrics for the FastAPI back-office.

Exposes three families at ``/metrics`` (Prometheus exposition format for
optional external scraping):

- ``api_http_requests_total``            — request counter (method, route, status)
- ``api_http_request_duration_seconds``  — latency histogram (method, route)
- ``arq_queue_depth``                    — ARQ jobs awaiting pickup per queue

Redis is optional at scrape time: if it is unreachable the queue gauge is
served as 0 and the process/HTTP metrics are still returned, so scraping can
never break the API.
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from shared.tasks import QUEUE_BOT, QUEUE_WORKER, queued_job_count

_REQUESTS = Counter(
    "api_http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "route", "status"],
)
_LATENCY = Histogram(
    "api_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "route"],
)
_QUEUE_DEPTH = Gauge("arq_queue_depth", "ARQ jobs awaiting pickup per queue", ["queue"])

# Don't instrument these (noise + self-recursion on /metrics).
_EXEMPT_PATHS = frozenset(
    {"/metrics", "/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect"}
)


def _route_template(request: Request) -> str:
    """Bounded-cardinality path label: the matched route template, or ``unmatched``."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path not in _EXEMPT_PATHS:
            route = _route_template(request)
            elapsed = time.perf_counter() - start
            _REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            _LATENCY.labels(request.method, route).observe(elapsed)
        return response


async def refresh_queue_depths() -> None:
    """Best-effort ARQ queue-depth refresh. Never raises."""
    for name, queue in (("worker", QUEUE_WORKER), ("bot", QUEUE_BOT)):
        _QUEUE_DEPTH.labels(name).set(await queued_job_count(queue))


async def metrics_response() -> Response:
    await refresh_queue_depths()
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
