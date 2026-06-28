"""Source channels CRUD + per-channel default-tag join management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_tenant_id, require_role
from api.schemas import (
    SourceChannelCreate,
    SourceChannelOut,
    SourceChannelUpdate,
)
from shared.config import get_settings
from shared.db import get_session
from shared.enums import PostState, Role
from shared.models import Admin, Post, SourceChannel, SourceChannelTag, Tag
from shared.tenant import scope_query, stamp_tenant

# States that are safe to cascade-delete (content is already finalised).
_TERMINAL_STATES = {PostState.published, PostState.rejected}

router = APIRouter(prefix="/source-channels", tags=["source-channels"])


async def _set_default_tag_links(
    session: AsyncSession, channel: SourceChannel, tag_ids: list[int]
) -> None:
    # Replace the join-table rows to mirror default_tag_ids.
    await session.execute(
        SourceChannelTag.__table__.delete().where(SourceChannelTag.source_channel_id == channel.id)
    )
    if tag_ids:
        # Validate all referenced tags exist.
        existing = {
            row[0]
            for row in (await session.execute(select(Tag.id).where(Tag.id.in_(tag_ids)))).all()
        }
        missing = set(tag_ids) - existing
        if missing:
            raise HTTPException(status_code=400, detail=f"unknown tag ids: {sorted(missing)}")
        session.add_all(
            [SourceChannelTag(source_channel_id=channel.id, tag_id=tid) for tid in tag_ids]
        )


@router.get("", response_model=list[SourceChannelOut])
async def list_channels(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.editor)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> list[SourceChannel]:
    stmt = scope_query(
        select(SourceChannel).order_by(SourceChannel.title), SourceChannel, tenant_id
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=SourceChannelOut, status_code=201)
async def create_channel(
    payload: SourceChannelCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> SourceChannel:
    settings = get_settings()
    channel = SourceChannel(
        telegram_channel_id=payload.telegram_channel_id,
        title=payload.title,
        username=payload.username,
        ingestion_enabled=payload.ingestion_enabled,
        policy=payload.policy,
        default_tag_ids=list(payload.default_tag_ids),
        normalization_template_id=payload.normalization_template_id,
        max_media_size_bytes=payload.max_media_size_bytes or settings.media_max_size_default,
        source_label=payload.source_label,
        # AI settings
        ai_enabled=payload.ai_enabled,
        ai_mode=payload.ai_mode,
        ai_target_language=payload.ai_target_language,
        ai_tone_prompt=payload.ai_tone_prompt,
        ai_custom_system_prompt=payload.ai_custom_system_prompt,
        watermark_enabled=payload.watermark_enabled,
        watermark_text=payload.watermark_text,
        strip_source_tags=payload.strip_source_tags,
    )
    stamp_tenant(channel, tenant_id)
    session.add(channel)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="channel already exists") from None
    await _set_default_tag_links(session, channel, list(payload.default_tag_ids))
    await session.commit()
    await session.refresh(channel)
    return channel


@router.patch("/{channel_id}", response_model=SourceChannelOut)
async def update_channel(
    channel_id: int,
    payload: SourceChannelUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> SourceChannel:
    channel = await session.get(SourceChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="source channel not found")
    if tenant_id is not None and channel.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="source channel not found")
    data = payload.model_dump(exclude_unset=True)
    for field in (
        "title",
        "username",
        "ingestion_enabled",
        "policy",
        "normalization_template_id",
        "max_media_size_bytes",
        "source_label",
        "ai_enabled",
        "ai_mode",
        "ai_target_language",
        "ai_tone_prompt",
        "ai_custom_system_prompt",
        "watermark_enabled",
        "watermark_text",
        "strip_source_tags",
    ):
        if field in data:
            setattr(channel, field, data[field])
    if data.get("default_tag_ids") is not None:
        channel.default_tag_ids = list(data["default_tag_ids"])
        await _set_default_tag_links(session, channel, list(data["default_tag_ids"]))
    await session.commit()
    await session.refresh(channel)
    return channel


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> None:
    channel = await session.get(SourceChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="source channel not found")

    # Refuse to cascade-delete posts that are still active (not yet terminal).
    active_count = int(
        (
            await session.scalar(
                select(func.count(Post.id)).where(
                    Post.source_channel_id == channel_id,
                    Post.state.not_in(_TERMINAL_STATES),
                )
            )
        )
        or 0
    )
    if active_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"channel has {active_count} active post(s) (not yet published or rejected). "
                "Reject or wait for them to complete before deleting the channel."
            ),
        )

    await session.delete(channel)
    await session.commit()
