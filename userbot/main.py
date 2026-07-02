"""Userbot entry point: connect, backfill, listen for new posts, run forever."""

from __future__ import annotations

import asyncio
import signal
from datetime import UTC, datetime

from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.errors import (
    AuthKeyError,
    FloodWaitError,
    PhoneNumberBannedError,
    SessionRevokedError,
    UserDeactivatedBanError,
)

from shared.config import get_settings
from shared.db import SessionLocal
from shared.health import start_health_server
from shared.logging import configure_logging, get_logger
from shared.models import SourceChannel
from userbot.client import build_client
from userbot.ingest import ingest_message, last_ingested_message_id, reconcile_pending

log = get_logger("userbot")

_FATAL_ERRORS = (AuthKeyError, SessionRevokedError, UserDeactivatedBanError, PhoneNumberBannedError)

_BACKFILL_LIMIT = 200

# ── MTProto liveness state ────────────────────────────────────────────────────
# Updated by the watchdog task; read by the health-check closure.
_mtproto_connected: bool = False
_mtproto_authorized: bool = False
_mtproto_last_ok: datetime | None = None  # timezone-aware (UTC)
_mtproto_failure_count: int = 0
_mtproto_failure_reason: str = ""

# Watchdog configuration.
_WATCHDOG_INTERVAL_SECONDS: int = 30
# A last_ok older than this threshold is considered stale (3x interval).
_WATCHDOG_STALE_SECONDS: int = _WATCHDOG_INTERVAL_SECONDS * 3  # 90 s
_CHANNEL_RELOAD_SECONDS: int = 300  # 5 minutes

# Set by run(), used by _watchdog to trigger a clean shutdown on fatal errors.
_stop_event: asyncio.Event | None = None


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


def _is_mtproto_healthy() -> tuple[bool, str]:
    """Return (healthy, reason) based on current module-level liveness state."""
    global _mtproto_connected, _mtproto_authorized, _mtproto_last_ok, _mtproto_failure_reason

    if not _mtproto_connected:
        return False, "disconnected"
    if not _mtproto_authorized:
        return False, "unauthorized"
    if _mtproto_last_ok is None:
        return False, "never_checked"
    age = (datetime.now(UTC) - _mtproto_last_ok).total_seconds()
    if age > _WATCHDOG_STALE_SECONDS:
        reason = _mtproto_failure_reason or "stale"
        return False, f"stale:{age:.0f}s ({reason})"
    return True, "ok"


async def _mtproto_check() -> tuple[bool, str]:
    """Extra health check passed to start_health_server."""
    ok, detail = _is_mtproto_healthy()
    return ok, detail


async def _watchdog(client: TelegramClient) -> None:
    """Periodically probe the MTProto connection and enqueue alerts on transitions.

    Fatal errors (session revoked, account banned) trigger a specific alert and
    shut the process down cleanly so Docker restarts it.  Consecutive failures
    use exponential backoff (30 s → 60 → 120 → 240 → 300 cap).
    """
    global _mtproto_connected, _mtproto_authorized, _mtproto_last_ok
    global _mtproto_failure_count, _mtproto_failure_reason

    from shared.tasks import enqueue_alert

    was_healthy: bool | None = None  # None = first cycle, no prior state

    while True:
        if _mtproto_failure_count > 0:
            backoff = min(
                _WATCHDOG_INTERVAL_SECONDS * (2 ** min(_mtproto_failure_count - 1, 4)),
                300,
            )
            await asyncio.sleep(backoff)
        else:
            await asyncio.sleep(_WATCHDOG_INTERVAL_SECONDS)

        connected = False
        authorized = False
        reason = ""

        try:
            connected = client.is_connected()
            _mtproto_connected = connected

            if connected:
                authorized = await client.is_user_authorized()
                _mtproto_authorized = authorized

            if connected and authorized:
                await client.get_me()
                _mtproto_last_ok = datetime.now(UTC)
                _mtproto_failure_count = 0
                _mtproto_failure_reason = ""
            else:
                reason = "disconnected" if not connected else "unauthorized"
                _mtproto_failure_count += 1
                _mtproto_failure_reason = reason
                log.warning(
                    "mtproto-watchdog-unhealthy",
                    connected=connected,
                    authorized=authorized,
                    failures=_mtproto_failure_count,
                )

        except _FATAL_ERRORS as exc:
            reason = type(exc).__name__
            _mtproto_failure_count += 1
            _mtproto_failure_reason = reason
            alert_text = (
                f"🚨 Userbot session TERMINATED: {reason} — "
                "manual re-login required "
                "(docker compose run --rm -it userbot python -m userbot.login)"
            )
            log.error("mtproto-fatal", error=reason)
            try:
                await enqueue_alert(alert_text)
            except Exception:
                log.exception("mtproto-fatal-alert-failed")
            if _stop_event is not None:
                _stop_event.set()
            return

        except FloodWaitError as exc:
            reason = f"floodwait:{exc.seconds}s"
            _mtproto_failure_count += 1
            _mtproto_failure_reason = reason
            log.warning("mtproto-watchdog-floodwait", seconds=exc.seconds, failures=_mtproto_failure_count)

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            reason = f"{type(exc).__name__}"
            _mtproto_failure_count += 1
            _mtproto_failure_reason = reason
            log.warning(
                "mtproto-watchdog-error",
                error=str(exc),
                exc_type=reason,
                failures=_mtproto_failure_count,
            )

        # ── Edge-triggered alerting ───────────────────────────────────────────
        now_healthy, detail = _is_mtproto_healthy()

        if was_healthy is None:
            was_healthy = now_healthy
            continue

        if was_healthy and not now_healthy:
            alert_text = f"⚠️ Userbot MTProto session unhealthy: {detail}"
            log.warning("mtproto-alert-unhealthy", detail=detail)
            try:
                await enqueue_alert(alert_text)
            except Exception:
                log.exception("mtproto-alert-enqueue-failed")

        elif not was_healthy and now_healthy:
            alert_text = "✅ Userbot MTProto session recovered and is healthy again."
            log.info("mtproto-alert-recovered")
            try:
                await enqueue_alert(alert_text)
            except Exception:
                log.exception("mtproto-alert-enqueue-failed")

        was_healthy = now_healthy


async def _channel_reloader(
    client: TelegramClient, channel_map: dict[int, SourceChannel]
) -> None:
    """Periodically refresh channel_map from the database so new/disabled channels
    are picked up without a container restart."""
    while True:
        await asyncio.sleep(_CHANNEL_RELOAD_SECONDS)
        try:
            channels = await load_channels()
            db_ids = {ch.telegram_channel_id for ch in channels}
            current_ids = set(channel_map.keys())

            for ch in channels:
                if ch.telegram_channel_id not in current_ids:
                    entity = await resolve_entity(client, ch)
                    if entity is not None:
                        channel_map[ch.telegram_channel_id] = ch
                        log.info("channel-added", channel_id=ch.id, tg_id=ch.telegram_channel_id)

            for tg_id in current_ids - db_ids:
                removed = channel_map.pop(tg_id)
                log.info("channel-removed", channel_id=removed.id, tg_id=tg_id)

        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("channel-reload-failed")


async def run() -> None:
    configure_logging("userbot")
    settings = get_settings()
    if not settings.bot_token and not settings.telegram_api_id:
        raise RuntimeError("userbot requires TELEGRAM_API_ID/TELEGRAM_API_HASH")

    global _stop_event
    _stop_event = asyncio.Event()

    client = build_client()
    try:
        await client.start(password=settings.telegram_2fa_password or None)  # type: ignore[arg-type]
    except _FATAL_ERRORS as exc:
        log.error("userbot-start-fatal", error=type(exc).__name__)
        from shared.tasks import enqueue_alert
        try:
            await enqueue_alert(
                f"🚨 Userbot cannot start: {type(exc).__name__} — "
                "manual re-login required "
                "(docker compose run --rm -it userbot python -m userbot.login)"
            )
        except Exception:
            pass
        raise SystemExit(1) from exc

    me = await client.get_me()
    log.info("userbot-connected", account=getattr(me, "username", None) or getattr(me, "id", None))

    # Initialise liveness state now that we know we are connected.
    global _mtproto_connected, _mtproto_authorized, _mtproto_last_ok
    _mtproto_connected = client.is_connected()
    _mtproto_authorized = True  # just confirmed by client.start() + get_me()
    _mtproto_last_ok = datetime.now(UTC)

    health = start_health_server(
        "userbot",
        settings.userbot_health_port,
        extra_checks={"mtproto": _mtproto_check},
    )

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
            log.warning("floodwait-live", seconds=e.seconds, msg_id=event.message.id)
            await asyncio.sleep(e.seconds + 1)
            try:
                await ingest_message(client, event.message, channel)
            except Exception:
                log.exception("ingest-retry-failed", msg_id=event.message.id)
        except Exception:
            log.exception("ingest-error-live", channel_id=channel.id, msg_id=event.message.id)

    log.info("listening", channels=len(channel_map))

    stop = _stop_event
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass

    watchdog = asyncio.create_task(_watchdog(client), name="mtproto-watchdog")
    reloader = asyncio.create_task(
        _channel_reloader(client, channel_map), name="channel-reloader"
    )
    task = asyncio.create_task(client.run_until_disconnected())
    _, pending = await asyncio.wait(
        {task, asyncio.create_task(stop.wait())}, return_when=asyncio.FIRST_COMPLETED
    )
    for t in pending:
        t.cancel()
    watchdog.cancel()
    reloader.cancel()
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
