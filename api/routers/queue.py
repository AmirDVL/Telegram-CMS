"""Draft-queue endpoints: list/get/edit/approve/schedule/reject.

These mirror the inline-button actions the aiogram bot performs in the editor
supergroup. Both surfaces write to the same `posts` rows and append
`post_events`; on approval they enqueue the same ARQ `publish` job the bot uses.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_admin, get_tenant_id
from api.schemas import (
    Paginated,
    PostDecision,
    PostEditTags,
    PostOut,
    PostSchedule,
)
from shared.db import get_session
from shared.enums import EventAction, PostState
from shared.models import Admin, Post, PostEvent
from shared.tasks import enqueue_publish
from shared.tenant import get_scoped, scope_query

router = APIRouter(prefix="/queue", tags=["queue"], dependencies=[Depends(get_current_admin)])


async def _get_post(session: AsyncSession, post_id: int, tenant_id: int | None) -> Post:
    post = await get_scoped(session, Post, post_id, tenant_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post not found")
    return post


async def _event(session: AsyncSession, post: Post, action: EventAction, actor: Admin, payload: dict) -> None:
    session.add(
        PostEvent(
            post_id=post.id,
            actor_admin_id=actor.id,
            action=action,
            payload=payload,
        )
    )


@router.get("", response_model=Paginated)
async def list_queue(
    state: list[PostState] | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Paginated:
    stmt = select(Post)
    count_stmt = select(func.count(Post.id))
    if state:
        stmt = stmt.where(Post.state.in_(state))
        count_stmt = count_stmt.where(Post.state.in_(state))
    stmt = scope_query(stmt, Post, tenant_id)
    count_stmt = scope_query(count_stmt, Post, tenant_id)
    total = int((await session.scalar(count_stmt)) or 0)
    result = await session.execute(
        stmt.order_by(Post.received_at.desc()).limit(limit).offset(offset)
    )
    items = list(result.scalars().all())
    return Paginated(items=items, total=total, limit=limit, offset=offset)


@router.get("/{post_id}", response_model=PostOut)
async def get_post(
    post_id: int,
    session: AsyncSession = Depends(get_session),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    return await _get_post(session, post_id, tenant_id)


@router.patch("/{post_id}/tags", response_model=PostOut)
async def edit_tags(
    post_id: int,
    payload: PostEditTags,
    session: AsyncSession = Depends(get_session),
    actor: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    post = await _get_post(session, post_id, tenant_id)
    post.tag_ids = list(payload.tag_ids)
    await _event(session, post, EventAction.edited, actor, {"tag_ids": post.tag_ids})
    await session.commit()
    await session.refresh(post)
    return post


async def _decide(
    post_id: int,
    decision: PostDecision,
    session: AsyncSession,
    actor: Admin,
    tenant_id: int | None = None,
) -> Post:
    post = await _get_post(session, post_id, tenant_id)
    if decision.tag_ids is not None:
        post.tag_ids = list(decision.tag_ids)

    if decision.action == "approve":
        post.state = PostState.approved
        post.scheduled_for = None
        await _event(session, post, EventAction.approved, actor, {"tag_ids": post.tag_ids})
        await session.commit()
        await enqueue_publish(post.id)
    elif decision.action == "schedule":
        if decision.scheduled_for is None:
            raise HTTPException(status_code=400, detail="scheduled_for is required")
        now = datetime.now(UTC)
        if decision.scheduled_for <= now:
            raise HTTPException(status_code=400, detail="scheduled_for must be in the future")
        post.state = PostState.scheduled
        post.scheduled_for = decision.scheduled_for
        await _event(
            session,
            post,
            EventAction.scheduled,
            actor,
            {"tag_ids": post.tag_ids, "scheduled_for": decision.scheduled_for.isoformat()},
        )
        await session.commit()
        delay = (decision.scheduled_for - now).total_seconds()
        await enqueue_publish(post.id, delay=delay)
    elif decision.action == "reject":
        post.state = PostState.rejected
        await _event(session, post, EventAction.rejected, actor, {"tag_ids": post.tag_ids})
        await session.commit()
    else:
        raise HTTPException(status_code=400, detail="action must be approve|schedule|reject")
    await session.refresh(post)
    return post


@router.post("/{post_id}/decision", response_model=PostOut)
async def decide(
    post_id: int,
    decision: PostDecision,
    session: AsyncSession = Depends(get_session),
    actor: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    return await _decide(post_id, decision, session, actor, tenant_id)


@router.post("/{post_id}/approve", response_model=PostOut)
async def approve(
    post_id: int,
    payload: PostEditTags | None = None,
    session: AsyncSession = Depends(get_session),
    actor: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    decision = PostDecision(
        action="approve",
        tag_ids=payload.tag_ids if payload else None,
    )
    return await _decide(post_id, decision, session, actor, tenant_id)


@router.post("/{post_id}/schedule", response_model=PostOut)
async def schedule(
    post_id: int,
    payload: PostSchedule,
    session: AsyncSession = Depends(get_session),
    actor: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    decision = PostDecision(action="schedule", scheduled_for=payload.scheduled_for)
    return await _decide(post_id, decision, session, actor, tenant_id)


@router.post("/{post_id}/reject", response_model=PostOut)
async def reject(
    post_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Post:
    decision = PostDecision(action="reject")
    return await _decide(post_id, decision, session, actor, tenant_id)
