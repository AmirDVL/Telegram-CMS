"""Admins CRUD (roles + enable/disable)."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import require_role
from api.schemas import AdminCreate, AdminOut, AdminUpdate
from shared.db import get_session
from shared.enums import Role
from shared.models import Admin
from shared.security import hash_password

router = APIRouter(prefix="/admins", tags=["admins"])


@router.get("", response_model=list[AdminOut])
async def list_admins(
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.admin)),
) -> list[Admin]:
    stmt = select(Admin).order_by(Admin.username)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=AdminOut, status_code=201)
async def create_admin(
    payload: AdminCreate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> Admin:
    admin = Admin(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        tg_user_id=payload.tg_user_id,
    )
    session.add(admin)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="username already exists") from None
    await session.refresh(admin)
    return admin


@router.patch("/{admin_id}", response_model=AdminOut)
async def update_admin(
    admin_id: int,
    payload: AdminUpdate,
    session: AsyncSession = Depends(get_session),
    _: Admin = Depends(require_role(Role.super_admin)),
) -> Admin:
    admin = await session.get(Admin, admin_id)
    if admin is None:
        raise HTTPException(status_code=404, detail="admin not found")
    if payload.password is not None:
        admin.password_hash = hash_password(payload.password)
    if payload.role is not None and payload.role != admin.role:
        if admin.role == Role.super_admin and payload.role != Role.super_admin:
            existing = (
                (
                    await session.execute(
                        select(Admin).where(
                            Admin.role == Role.super_admin, Admin.disabled_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(list(existing)) <= 1:
                raise HTTPException(status_code=400, detail="cannot demote the last super-admin")
        admin.role = payload.role
    if payload.disabled is not None:
        if payload.disabled and admin.role == Role.super_admin and admin.disabled_at is None:
            active_super = (
                (
                    await session.execute(
                        select(Admin).where(
                            Admin.role == Role.super_admin, Admin.disabled_at.is_(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            if len(list(active_super)) <= 1:
                raise HTTPException(
                    status_code=400, detail="cannot disable the last active super-admin"
                )
        admin.disabled_at = datetime.now(UTC) if payload.disabled else None
    data = payload.model_dump(exclude_unset=True)
    if "tg_user_id" in data:
        admin.tg_user_id = data["tg_user_id"]
    await session.commit()
    await session.refresh(admin)
    return admin
