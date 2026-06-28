"""Userbot entry point: connect, backfill, listen for new posts, run forever."""

from __future__ import annotations

import asyncio
import signal

from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError

from shared.config import get_settings
from shared.db import SessionLocal
from shared.health import start_health_server
from shared.logging import configure_logging, get_logger
from shared.models import SourceChannel
from userbot.client import build_client
from userbot.ingest import ingest_message, last_ingested_message_id, reconcile_pending

log = get_logger("userbot")

_BACKFILL_LIMIT = 200


async def load_channels() -> list[SourceChannel]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(SourceChannel).where(SourceChannel.ingestion_enabled.is_(True))
        )
        return list(result.scalars().all())


async def resolve_entity(client: TelegramClient, channel: SourceChannel):
    try:
        return await client.get_entity(channel.telegram_channel_id)
    except Exception as e:
        log.error(
            "entity-resolve-failed",
            channel_id=channel.id,
            tg_id=channel.telegram_channel_id,
            error=str(e),
        )
        return None


async def backfill(client: TelegramClient, channel: SourceChannel, entity) -> None:
    last_id = await last_ingested_message_id(channel)
    count = 0
    try:
        async for msg in client.iter_messages(
            entity, min_id=last_id, reverse=True, limit=_BACKFILL_LIMIT
        ):
            try:
                await ingest_message(client, msg, channel)
                count += 1
            except FloodWaitError as e:
                log.warning("floodwait-backfill", seconds=e.seconds)
                await asyncio.sleep(e.seconds + 1)
            except Exception:
                log.exception("ingest-error-backfill", channel_id=channel.id, msg_id=msg.id)
    except Exception:
        log.exception("backfill-failed", channel_id=channel.id)
    if count:
        log.info("backfilled", channel_id=channel.id, count=count)


async def run() -> None:
    configure_logging("userbot")
    settings = get_settings()
    if not settings.bot_token and not settings.telegram_api_id:
        raise RuntimeError("userbot requires TELEGRAM_API_ID/TELEGRAM_API_HASH")

    client = build_client()
    await client.start(password=settings.telegram_2fa_password or None)  # type: ignore[arg-type]
    me = await client.get_me()
    log.info("userbot-connected", account=getattr(me, "username", None) or getattr(me, "id", None))

    health = start_health_server("userbot", settings.userbot_health_port)

    try:
        orphans = await reconcile_pending()
        if orphans:
            log.info("reconciled-pending", count=orphans)
    except Exception:
        log.exception("reconcile-pending-failed")

    channels = await load_channels()
    if not channels:
        log.warning("no-enabled-source-channels")
    channel_map: dict[int, SourceChannel] = {}
    for channel in channels:
        entity = await resolve_entity(client, channel)
        if entity is None:
            continue
        channel_map[channel.telegram_channel_id] = channel
        await backfill(client, channel, entity)

    @client.on(events.NewMessage())
    async def on_new_message(event):  # type: ignore[no-untyped-def]
        channel = channel_map.get(event.chat_id)
        if channel is None:
            return
        try:
            await ingest_message(client, event.message, channel)
        except FloodWaitError as e:
            log.warning("floodwait-live", seconds=e.seconds)
            await asyncio.sleep(e.seconds + 1)
        except Exception:
            log.exception("ingest-error-live", channel_id=channel.id, msg_id=event.message.id)

    log.info("listening", channels=len(channel_map))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    task = asyncio.create_task(client.run_until_disconnected())
    _, pending = await asyncio.wait(
        {task, asyncio.create_task(stop.wait())}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    health.cancel()
    await client.disconnect()
    log.info("userbot-stopped")


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
