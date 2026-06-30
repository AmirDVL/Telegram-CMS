"""ARQ job registry + enqueue helpers, shared by worker and bot.

Job names are constants and **must equal the registered consumer function's
``__name__``** (ARQ routes jobs by function name). Producers (userbot, bot
callbacks, api) use the ``enqueue_*`` helpers.

Two queues keep ownership clean (a worker never dequeues a job whose function
it does not own, which would otherwise fail it):

- ``QUEUE_WORKER`` → consumed by the `worker` service: ``normalize``, ``prune_dedupe``.
- ``QUEUE_BOT``    → consumed by the `bot` service:    ``publish``, ``post_draft``.
"""

from __future__ import annotations

import json
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job

from shared.config import get_settings


# ── JSON job (de)serialization ───────────────────────────────────────────────
# ARQ defaults to pickle, which is Python-only. We use JSON instead so that
# non-Python producers/consumers (notably the Go back-office API, which enqueues
# `publish` jobs) can read and write the same job + result payloads. The wire
# format is unchanged otherwise: a job is ``json({t, f, a, k, et})`` stored under
# ``arq:job:<id>`` plus a sorted-set entry on the queue (see the Go enqueue in
# apigo/enqueue.go). All job args/kwargs in this codebase are JSON-serializable
# (ints, strings, None). Both the producer pool (below) AND every consuming
# Worker (worker/main.py, bot/main.py) MUST use these so the formats agree.
def arq_job_serializer(data: dict) -> bytes:
    # default=str keeps result serialization from failing on odd types
    # (e.g. datetimes); job args here are already JSON-native.
    return json.dumps(data, default=str).encode()


def arq_job_deserializer(data: bytes) -> dict:
    return json.loads(data)

# ── Job names (== consumer function __name__) ────────────────────────────────
JOB_NORMALIZE = "normalize"
JOB_PUBLISH = "publish"
JOB_POST_DRAFT = "post_draft"
JOB_PRUNE_DEDUPE = "prune_dedupe"
JOB_ALERT = "alert"

# ── Queues ───────────────────────────────────────────────────────────────────
QUEUE_WORKER = "arq:queue:worker"
QUEUE_BOT = "arq:queue:bot"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


# Process-wide shared ARQ pool. Reused across enqueues so the userbot's backfill
# (and per-message ingestion) doesn't open/close a Redis connection per job.
_pool = None


async def _get_pool():
    global _pool
    if _pool is None:
        _pool = await create_pool(
            redis_settings(),
            job_serializer=arq_job_serializer,
            job_deserializer=arq_job_deserializer,
        )
    return _pool


# ── Producers ────────────────────────────────────────────────────────────────
async def enqueue_job(
    name: str, *args: Any, queue: str | None = None, delay: float | None = None, **kwargs: Any
) -> Job | None:
    global _pool
    try:
        redis = await _get_pool()
        enqueue_kwargs: dict[str, Any] = {}
        if queue is not None:
            enqueue_kwargs["_queue_name"] = queue
        if delay is not None:
            enqueue_kwargs["_defer_by"] = delay
        return await redis.enqueue_job(name, *args, **enqueue_kwargs, **kwargs)
    except (ConnectionError, OSError):
        # Drop the stale pool so the next call recreates it.
        _pool = None
        raise


async def enqueue_normalize(post_id: int) -> Job | None:
    return await enqueue_job(JOB_NORMALIZE, post_id, queue=QUEUE_WORKER)


async def enqueue_publish(post_id: int, *, delay: float | None = None) -> Job | None:
    return await enqueue_job(JOB_PUBLISH, post_id, queue=QUEUE_BOT, delay=delay)


async def enqueue_post_draft(post_id: int) -> Job | None:
    return await enqueue_job(JOB_POST_DRAFT, post_id, queue=QUEUE_BOT)


async def enqueue_prune_dedupe() -> Job | None:
    return await enqueue_job(JOB_PRUNE_DEDUPE, queue=QUEUE_WORKER)


async def enqueue_alert(text: str, *, tenant_id: int | None = None) -> Job | None:
    """Enqueue an alert message to be sent by the bot to the editor group.

    The ``alert`` consumer in ``bot/alerts.py`` picks this up from ``QUEUE_BOT``.
    ``tenant_id`` is forwarded so the bot can resolve the correct editor group
    and bot token in multi-tenant deployments.
    """
    return await enqueue_job(JOB_ALERT, text, queue=QUEUE_BOT, tenant_id=tenant_id)


async def queued_job_count(queue: str) -> int:
    """Number of jobs waiting in an ARQ queue (``ZCARD`` of its sorted set).

    ARQ stores each queue's pending + delayed jobs in a sorted set keyed by the
    queue name, so this is the count of jobs not yet picked up by a worker.
    Used by the API ``/metrics`` endpoint to expose broker depth. Returns 0 if
    Redis is unreachable — observability must never break the request path.
    """
    try:
        redis = await _get_pool()
        return int(await redis.zcard(queue))
    except Exception:
        return 0
