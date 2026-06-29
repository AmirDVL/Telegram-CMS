"""Tenant management endpoints (platform super-admin only).

Only active when ``MULTI_TENANCY_ENABLED=true``. Each endpoint checks the flag
and returns 404 when multi-tenancy is off, so the routes are harmlessly
registered but invisible.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_role
from api.schemas import TenantCreate, TenantOut, TenantUpdate
from shared.config import get_settings
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin, Tenant

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _check_mt():
    if not get_settings().multi_tenancy_enabled:
        raise HTTPException(status_code=404, detail="multi-tenancy is not enabled")


@router.get("", response_model=list[TenantOut])
async def list_tenants(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> list[Tenant]:
    _check_mt()
    result = await session.execute(select(Tenant).order_by(Tenant.name))
    return list(result.scalars().all())


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_tenant(
    tenant_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> Tenant:
    _check_mt()
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant


@router.post("", response_model=TenantOut, status_code=201)
async def create_tenant(
    payload: TenantCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> Tenant:
    _check_mt()
    tenant = Tenant(
        slug=payload.slug,
        name=payload.name,
        bot_token=payload.bot_token,
        destination_channel_id=payload.destination_channel_id,
        editor_group_id=payload.editor_group_id,
        ai_enabled=payload.ai_enabled,
        ai_mode=payload.ai_mode,
        ai_target_language=payload.ai_target_language,
        ai_tone_prompt=payload.ai_tone_prompt,
        ai_custom_system_prompt=payload.ai_custom_system_prompt,
        watermark_enabled=payload.watermark_enabled,
        watermark_text=payload.watermark_text,
        strip_source_tags=payload.strip_source_tags,
        # Per-tenant config overrides.
        ai_model=payload.ai_model,
        ai_max_tokens=payload.ai_max_tokens,
        ai_timeout_seconds=payload.ai_timeout_seconds,
        dedupe_lookback_days=payload.dedupe_lookback_days,
        publish_spacing_seconds=payload.publish_spacing_seconds,
        media_max_size_bytes=payload.media_max_size_bytes,
    )
    session.add(tenant)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="tenant slug already exists") from None
    await session.refresh(tenant)
    return tenant


@router.patch("/{tenant_id}", response_model=TenantOut)
async def update_tenant(
    tenant_id: int,
    payload: TenantUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> Tenant:
    _check_mt()
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    data = payload.model_dump(exclude_unset=True)
    for field in (
        "name",
        "bot_token",
        "destination_channel_id",
        "editor_group_id",
        "ai_enabled",
        "ai_mode",
        "ai_target_language",
        "ai_tone_prompt",
        "ai_custom_system_prompt",
        "watermark_enabled",
        "watermark_text",
        "strip_source_tags",
        # Per-tenant config overrides.
        "ai_model",
        "ai_max_tokens",
        "ai_timeout_seconds",
        "dedupe_lookback_days",
        "publish_spacing_seconds",
        "media_max_size_bytes",
    ):
        if field in data:
            setattr(tenant, field, data[field])

    if data.get("disabled") is not None:
        tenant.disabled_at = datetime.now(UTC) if data["disabled"] else None

    await session.commit()
    await session.refresh(tenant)
    return tenant


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> None:
    _check_mt()
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found")
    # Soft-delete: disable rather than hard-delete to preserve referential integrity.
    tenant.disabled_at = datetime.now(UTC)
    await session.commit()
