"""Bot entry point: aiogram polling + the embedded ARQ `publish`/`post_draft` worker.

Both run in one asyncio loop: the Dispatcher handles admin commands + inline
callbacks (and enqueues `publish`), while the ARQ worker consumes `publish` and
`post_draft` from the bot queue. This keeps the bot the sole owner of Telegram
publishing (plan §3).
"""

from __future__ import annotations

import asyncio
import signal

from aiogram import Bot, Dispatcher
from arq.connections import RedisSettings
from arq.worker import create_worker

from bot.alerts import alert
from bot.client import get_bot
from bot.draft import post_draft
from bot.handlers import admin_router, callback_router
from bot.publisher import publish
from shared.config import get_settings
from shared.health import start_health_server
from shared.logging import configure_logging, get_logger
from shared.tasks import (
    QUEUE_BOT,
    arq_job_deserializer,
    arq_job_serializer,
    redis_settings,
)

log = get_logger("bot")


class BotWorkerSettings:
    functions = [publish, post_draft, alert]
    queue_name = QUEUE_BOT
    redis_settings: RedisSettings = redis_settings()
    # JSON (de)serializer so the queue is language-agnostic (see shared/tasks.py);
    # lets the Go API enqueue `publish` jobs this worker consumes.
    job_serializer = staticmethod(arq_job_serializer)
    job_deserializer = staticmethod(arq_job_deserializer)
    max_jobs = get_settings().max_concurrent_publishes
    job_timeout = 900
    retry_jobs = True


async def run() -> None:
    configure_logging("bot")
    settings = get_settings()
    bot: Bot = get_bot()
    dp = Dispatcher()
    dp.include_router(admin_router)
    dp.include_router(callback_router)

    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    log.info("bot-starting", username=me.username, queue=QUEUE_BOT)
    health = start_health_server("bot", settings.bot_health_port)

    worker = create_worker(BotWorkerSettings)
    polling = asyncio.create_task(dp.start_polling(bot), name="polling")
    arq = asyncio.create_task(worker.async_run(), name="arq")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    waiter = asyncio.create_task(stop.wait(), name="stop")
    try:
        _, pending = await asyncio.wait(
            {polling, arq, waiter}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for t in pending:
            t.cancel()
        health.cancel()
        await worker.close()
        await bot.session.close()
        log.info("bot-stopped")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
