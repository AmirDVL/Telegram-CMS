"""FastAPI dependencies: DB session + JWT-based admin + role gating + tenant scope."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db import get_session
from shared.enums import Role, role_at_least
from shared.models import Admin
from shared.security import TokenClaims, decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# Store the decoded claims on the request so downstream deps can read tenant_id
# without decoding the token twice.
_claims_cache: dict[str, TokenClaims] = {}


async def _get_claims(token: str | None = Depends(oauth2_scheme)) -> TokenClaims:
    if not token:
        raise CREDENTIALS
    claims = decode_token(token)
    if claims is None or claims.token_type != "access":
        raise CREDENTIALS
    return claims


async def get_current_admin(
    claims: TokenClaims = Depends(_get_claims),
    session: AsyncSession = Depends(get_session),
) -> Admin:
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


async def get_tenant_id(claims: TokenClaims = Depends(_get_claims)) -> int | None:
    """Extract the tenant_id from the current JWT.

    Returns ``None`` when multi-tenancy is off or the admin is a platform-level
    super-admin (no tenant scope). All routers that need tenant scoping inject
    this dependency.
    """
    return claims.tenant_id
