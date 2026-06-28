"""Tags CRUD (controlled vocabulary)."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_role
from api.schemas import TagCreate, TagOut, TagUpdate
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin, Post, Tag

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
) -> list[Tag]:
    result = await session.execute(select(Tag).order_by(Tag.label))
    return list(result.scalars().all())


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(
    payload: TagCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> Tag:
    tag = Tag(slug=_slugify(payload.slug), label=payload.label, color=payload.color)
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
) -> Tag:
    tag = await session.get(Tag, tag_id)
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
) -> None:
    tag = await session.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="tag not found")

    # Strip the deleted tag id from every post's tag_ids array so stale ids
    # don't accumulate.  array_remove is a no-op for posts that don't have it.
    await session.execute(
        update(Post)
        .where(func.array_position(Post.tag_ids, tag_id).isnot(None))
        .values(tag_ids=func.array_remove(Post.tag_ids, tag_id))
        .execution_options(synchronize_session=False)
    )

    await session.delete(tag)
    await session.commit()


@router.get("/count")
async def count_tags(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    total = await session.scalar(select(func.count(Tag.id)))
    return {"total": int(total or 0)}
