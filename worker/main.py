"""ARQ worker entry point: registers `normalize` + `prune_dedupe` (worker queue).

Publishing (`publish`) and draft-card posting (`post_draft`) are consumed by the
`bot` service on a separate queue, keeping the bot the sole owner of Telegram
interactions.
"""

from __future__ import annotations

from arq.connections import RedisSettings
from arq.cron import cron

from shared.config import get_settings
from shared.health import start_health_server
from shared.logging import configure_logging, get_logger
from shared.tasks import QUEUE_WORKER, redis_settings
from worker.normalize import normalize
from worker.reconcile import prune_dedupe, reconcile_scheduled


async def on_startup(ctx: dict) -> None:
    configure_logging("worker")
    log = get_logger("worker")
    log.info("worker-starting", queue=QUEUE_WORKER)
    start_health_server("worker", get_settings().worker_health_port)
    try:
        await reconcile_scheduled()
    except Exception:
        log.exception("reconcile-failed")


async def on_shutdown(ctx: dict) -> None:
    get_logger("worker").info("worker-stopping")


class WorkerSettings:
    functions = [normalize, prune_dedupe]
    queue_name = QUEUE_WORKER
    redis_settings: RedisSettings = redis_settings()
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = get_settings().max_concurrent_publishes + 4
    job_timeout = 600
    retry_jobs = True
    # Daily housekeeping: prune the dedupe lookback index + orphaned media.
    cron_jobs = [
        cron(prune_dedupe, hour=4, minute=0, run_at_startup=False),
    ]
