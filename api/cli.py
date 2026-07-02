"""Operational CLI: `migrate`, `seed-admin`, `seed-tags` (templates/tags defaults)."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from shared.config import get_settings
from shared.db import SessionLocal
from shared.enums import Role
from shared.logging import configure_logging, get_logger
from shared.models import Admin, Tag, Template
from shared.normalize import DEFAULT_TEMPLATE_BODY
from shared.security import hash_password

DEFAULT_TEMPLATE = DEFAULT_TEMPLATE_BODY

DEFAULT_TAGS = [
    ("news", "News", "#1f77b4"),
    ("tech", "Tech", "#17becf"),
    ("crypto", "Crypto", "#f7931a"),
    ("business", "Business", "#2ca02c"),
    ("breaking", "Breaking", "#d62728"),
    ("culture", "Culture", "#9467bd"),
    ("sports", "Sports", "#e377c2"),
]


async def _seed_admin() -> None:
    settings = get_settings()
    if not settings.seed_admin_username or not settings.seed_admin_password:
        return
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(Admin).where(Admin.username == settings.seed_admin_username)
        )
        if existing is not None:
            return
        session.add(
            Admin(
                username=settings.seed_admin_username,
                password_hash=hash_password(settings.seed_admin_password),
                role=Role.super_admin,
            )
        )
        await session.commit()


async def _seed_defaults() -> None:
    async with SessionLocal() as session:
        # Default template
        if (await session.scalar(select(Template).where(Template.name == "Default"))) is None:
            tpl = Template(name="Default", body=DEFAULT_TEMPLATE)
            session.add(tpl)
        # Default tag vocabulary
        existing_slugs = {
            r[0] for r in (await session.execute(select(Tag.slug))).all()
        }
        for slug, label, color in DEFAULT_TAGS:
            if slug not in existing_slugs:
                tag = Tag(slug=slug, label=label, color=color)
                session.add(tag)
        await session.commit()


async def amain(cmd: str) -> int:
    """Handles the async-only commands. `migrate` is handled in main() because
    Alembic runs synchronously (env.py manages its own event loop)."""
    configure_logging("api-cli")
    log = get_logger("cli")

    if cmd == "seed-admin":
        await _seed_admin()
        log.info("seed-admin-done")
    elif cmd == "seed-defaults":
        await _seed_defaults()
        log.info("seed-defaults-done")
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print("usage: python -m api.cli [migrate|seed-admin|seed-defaults]", file=sys.stderr)
        return 2
    return 0


def _run_migrations() -> None:
    """Apply Alembic migrations to head. Synchronous — env.py manages its own loop."""
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


async def _seed_all() -> None:
    await _seed_admin()
    await _seed_defaults()


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "migrate"
    if cmd == "migrate":
        # Run alembic on a plain synchronous path (no running loop), then seed.
        configure_logging("api-cli")
        log = get_logger("cli")
        _run_migrations()
        log.info("migrations-applied")
        asyncio.run(_seed_all())
        log.info("seed-complete")
        return
    sys.exit(asyncio.run(amain(cmd)))


if __name__ == "__main__":
    main()
