"""First-run interactive login for the userbot.

Run once, interactively, to create the persistent ``.session`` file in the
session volume (Telethon prompts for phone → login code → 2FA password):

    docker compose run --rm -it userbot python -m userbot.login
"""

from __future__ import annotations

import asyncio
import sys

from shared.logging import configure_logging, get_logger
from userbot.client import build_client


async def login() -> int:
    configure_logging("userbot-login")
    log = get_logger("userbot.login")
    client = build_client()
    # Interactive start: Telethon will prompt on stdin for phone/code/2FA.
    await client.start()  # type: ignore[call-arg]
    me = await client.get_me()
    log.info(
        "login-ok",
        account=getattr(me, "username", None) or getattr(me, "id", None),
        first_name=getattr(me, "first_name", None),
    )
    await client.disconnect()
    print("Session saved. You can now start the userbot service.", file=sys.stderr)
    return 0


def main() -> None:
    sys.exit(asyncio.run(login()))


if __name__ == "__main__":
    main()
