"""Templates CRUD (Jinja2 normalization templates)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_role
from api.schemas import TemplateCreate, TemplateOut, TemplateUpdate
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin, Template

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.editor)),
) -> list[Template]:
    result = await session.execute(select(Template).order_by(Template.name))
    return list(result.scalars().all())


@router.post("", response_model=TemplateOut, status_code=201)
async def create_template(
    payload: TemplateCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> Template:
    tpl = Template(name=payload.name, body=payload.body)
    session.add(tpl)
    await session.commit()
    await session.refresh(tpl)
    return tpl


@router.patch("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int,
    payload: TemplateUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> Template:
    tpl = await session.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    if payload.name is not None:
        tpl.name = payload.name
    if payload.body is not None:
        tpl.body = payload.body
    await session.commit()
    await session.refresh(tpl)
    return tpl


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: int,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> None:
    tpl = await session.get(Template, template_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail="template not found")
    await session.delete(tpl)
    await session.commit()
