"""FastAPI dependencies: DB session + JWT-based admin + role gating."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_session
from shared.enums import Role, role_at_least
from shared.models import Admin
from shared.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_admin(
    token: str | None = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> Admin:
    if not token:
        raise CREDENTIALS
    claims = decode_token(token)
    if claims is None or claims.token_type != "access":
        raise CREDENTIALS

    result = await session.execute(
        select(Admin).where(Admin.id == claims.admin_id, Admin.disabled_at.is_(None))
    )
    admin = result.scalar_one_or_none()
    if admin is None:
        raise CREDENTIALS
    return admin


def require_role(required: Role):
    """Dependency factory: enforce that the authenticated admin has `required` role or higher."""

    async def _dep(admin: Admin = Depends(get_current_admin)) -> Admin:
        if not role_at_least(admin.role, required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return admin

    return _dep
