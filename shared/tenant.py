"""Tenant isolation helpers for multi-tenancy.

When ``MULTI_TENANCY_ENABLED=false`` (the default), every helper is a **no-op**:
``scope_query`` returns the query unchanged, ``stamp_tenant`` does nothing, and
``get_tenant_from_post`` returns ``None``.  This keeps the rest of the codebase
free from ``if multi_tenancy_enabled:`` conditionals — callers just call the
helpers unconditionally.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger("shared.tenant")

T = TypeVar("T")


def is_multi_tenant() -> bool:
    """Return True only when multi-tenancy is explicitly enabled."""
    return get_settings().multi_tenancy_enabled


def scope_query(stmt: Select[T], model, tenant_id: int | None) -> Select[T]:
    """Append ``WHERE model.tenant_id == tenant_id`` if multi-tenancy is on.

    When disabled, or when ``tenant_id`` is ``None`` (platform super-admin),
    the query is returned unchanged — giving full cross-tenant visibility.
    """
    if not is_multi_tenant() or tenant_id is None:
        return stmt
    return stmt.where(model.tenant_id == tenant_id)


def stamp_tenant(instance, tenant_id: int | None) -> None:
    """Set ``tenant_id`` on a new ORM instance before insert.

    No-op when multi-tenancy is off or ``tenant_id`` is ``None``.
    """
    if is_multi_tenant() and tenant_id is not None:
        instance.tenant_id = tenant_id


async def get_tenant_for_channel(session: AsyncSession, channel_id: int):
    """Resolve the Tenant row for a source channel (if any).

    Used by the worker and bot to look up tenant-specific settings (bot token,
    destination channel, AI overrides) at runtime.
    """
    if not is_multi_tenant():
        return None

    from shared.models import SourceChannel, Tenant

    channel = await session.get(SourceChannel, channel_id)
    if channel is None or channel.tenant_id is None:
        return None
    return await session.get(Tenant, channel.tenant_id)
