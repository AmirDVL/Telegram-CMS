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

from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from arq.jobs import Job

from shared.config import get_settings

# ── Job names (== consumer function __name__) ────────────────────────────────
JOB_NORMALIZE = "normalize"
JOB_PUBLISH = "publish"
JOB_POST_DRAFT = "post_draft"
JOB_PRUNE_DEDUPE = "prune_dedupe"

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
        _pool = await create_pool(redis_settings())
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
