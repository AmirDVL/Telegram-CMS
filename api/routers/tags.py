"""Tags CRUD (controlled vocabulary)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_admin, get_tenant_id, require_role
from api.schemas import TagCreate, TagOut, TagUpdate
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin, Post, Tag
from shared.tenant import get_scoped, scope_query, stamp_tenant

router = APIRouter(prefix="/tags", tags=["tags"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=400, detail="invalid slug")
    return slug[:64]


@router.get("", response_model=list[TagOut])
async def list_tags(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.editor)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> list[Tag]:
    stmt = scope_query(select(Tag).order_by(Tag.label), Tag, tenant_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Tag:
    tag = Tag(slug=_slugify(payload.slug), label=payload.label, color=payload.color)
    stamp_tenant(tag, tenant_id)
    session.add(tag)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="slug already exists") from None
    await session.refresh(tag)
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: int,
    payload: TagUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> Tag:
    tag = await get_scoped(session, Tag, tag_id, tenant_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")
    if payload.label is not None:
        tag.label = payload.label
    if payload.color is not None:
        tag.color = payload.color
    await session.commit()
    await session.refresh(tag)
    return tag


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    tag_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
    tenant_id: int | None = Depends(get_tenant_id),
) -> None:
    tag = await get_scoped(session, Tag, tag_id, tenant_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")

    # Strip the deleted tag id from every post's tag_ids array so stale ids
    # don't accumulate.  array_remove is a no-op for posts that don't have it.
    # Scope the update to the caller's tenant so we never touch another tenant's posts.
    stmt = (
        update(Post)
        .where(func.array_position(Post.tag_ids, tag_id).isnot(None))
        .values(tag_ids=func.array_remove(Post.tag_ids, tag_id))
        .execution_options(synchronize_session=False)
    )
    stmt = scope_query(stmt, Post, tenant_id)
    await session.execute(stmt)

    await session.delete(tag)
    await session.commit()


@router.get("/count")
async def count_tags(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(get_current_admin),
    tenant_id: int | None = Depends(get_tenant_id),
) -> dict[str, int]:
    stmt = scope_query(select(func.count(Tag.id)), Tag, tenant_id)
    total = await session.scalar(stmt)
    return {"total": int(total or 0)}
