"""AI settings endpoints: get/update per-channel AI config + dry-run test."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_tenant_id, require_role
from api.schemas import AISettingsOut, AISettingsUpdate, AITestRequest, AITestResponse
from shared.config import get_settings
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin, SourceChannel
from shared.transform import AITransformError, transform_text

router = APIRouter(prefix="/source-channels", tags=["ai-settings"])


@router.get("/{channel_id}/ai", response_model=AISettingsOut)
async def get_ai_settings(
    channel_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.editor)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> AISettingsOut:
    channel = await session.get(SourceChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="source channel not found")
    if tenant_id is not None and channel.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="source channel not found")
    return AISettingsOut.model_validate(channel)


@router.patch("/{channel_id}/ai", response_model=AISettingsOut)
async def update_ai_settings(
    channel_id: int,
    payload: AISettingsUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> AISettingsOut:
    channel = await session.get(SourceChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="source channel not found")
    if tenant_id is not None and channel.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="source channel not found")

    data = payload.model_dump(exclude_unset=True)
    for field in (
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

    await session.commit()
    await session.refresh(channel)
    return AISettingsOut.model_validate(channel)


@router.post("/{channel_id}/ai/test", response_model=AITestResponse)
async def test_ai_transform(
    channel_id: int,
    payload: AITestRequest,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.editor)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> AITestResponse:
    """Dry-run: send sample text through the LLM and return the result.

    Uses the channel's configured settings unless overridden in the request.
    """
    settings = get_settings()
    if not settings.ai_enabled:
        raise HTTPException(status_code=400, detail="AI transformation is globally disabled")
    if not settings.ai_api_key:
        raise HTTPException(status_code=400, detail="AI_API_KEY is not configured")

    channel = await session.get(SourceChannel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="source channel not found")
    if tenant_id is not None and channel.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="source channel not found")

    # Use request payload overrides, fall back to channel settings.
    mode = payload.mode
    target_language = payload.target_language or channel.ai_target_language
    tone_prompt = payload.tone_prompt or channel.ai_tone_prompt
    custom_system_prompt = payload.custom_system_prompt or channel.ai_custom_system_prompt

    try:
        result = await transform_text(
            payload.text,
            mode=mode,
            target_language=target_language,
            tone_prompt=tone_prompt,
            custom_system_prompt=custom_system_prompt,
        )
    except AITransformError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return AITestResponse(
        original=payload.text,
        transformed=result.text,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        latency_ms=result.latency_ms,
    )
