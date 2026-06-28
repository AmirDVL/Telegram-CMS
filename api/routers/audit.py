"""Audit log (post_events) read endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_admin, get_tenant_id
from api.schemas import Paginated, PostEventOut
from shared.db import get_session
from shared.enums import EventAction
from shared.models import PostEvent
from shared.tenant import scope_query

router = APIRouter(prefix="/audit", tags=["audit"], dependencies=[Depends(get_current_admin)])


@router.get("", response_model=Paginated)
async def list_events(
    post_id: int | None = Query(default=None),
    action: list[EventAction] | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Paginated:
    stmt = select(PostEvent)
    count_stmt = select(func.count(PostEvent.id))
    if post_id is not None:
        stmt = stmt.where(PostEvent.post_id == post_id)
        count_stmt = count_stmt.where(PostEvent.post_id == post_id)
    if action:
        stmt = stmt.where(PostEvent.action.in_(action))
        count_stmt = count_stmt.where(PostEvent.action.in_(action))
    stmt = scope_query(stmt, PostEvent, tenant_id)
    count_stmt = scope_query(count_stmt, PostEvent, tenant_id)
    total = int((await session.scalar(count_stmt)) or 0)
    result = await session.execute(
        stmt.order_by(PostEvent.created_at.desc()).limit(limit).offset(offset)
    )
    items = list(result.scalars().all())
    return Paginated(items=items, total=total, limit=limit, offset=offset)


@router.get("/post/{post_id}", response_model=list[PostEventOut])
async def list_post_events(
    post_id: int, session: AsyncSession = Depends(get_session)
) -> list[PostEvent]:
    result = await session.execute(
        select(PostEvent)
        .where(PostEvent.post_id == post_id)
        .order_by(PostEvent.created_at.asc())
    )
    return list(result.scalars().all())
