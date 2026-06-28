"""Auth router: login (form + JSON), refresh, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_admin
from api.limiter import limiter
from api.schemas import AdminOut, LoginIn, RefreshIn, TokenOut
from shared.config import get_settings
from shared.db import get_session
from shared.models import Admin
from shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Cookie name used for the httpOnly refresh token.
_REFRESH_COOKIE = "refresh_token"


async def _authenticate(session: AsyncSession, username: str, password: str) -> Admin:
    result = await session.execute(
        select(Admin).where(Admin.username == username, Admin.disabled_at.is_(None))
    )
    admin = result.scalar_one_or_none()
    if admin is None or not verify_password(password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    if needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(password)
        await session.commit()
    return admin


def _tokens(admin: Admin) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(
            admin.id, admin.username, admin.role, tenant_id=admin.tenant_id
        ),
        refresh_token=create_refresh_token(
            admin.id, admin.username, admin.role, tenant_id=admin.tenant_id
        ),
    )


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    """Attach the refresh token as an httpOnly cookie so it is never accessible
    to JavaScript. `secure` is set in production; `samesite=lax` is safe for
    same-site requests and works on localhost across ports in modern browsers."""
    settings = get_settings()
    is_production = settings.app_domain not in ("localhost", "")
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=settings.refresh_token_ttl_days * 86_400,
        path="/api/auth",  # Scope cookie to auth endpoints only.
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_REFRESH_COOKIE,
        path="/api/auth",
        httponly=True,
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit("10/minute")
async def login_json(
    request: Request,
    payload: LoginIn,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    admin = await _authenticate(session, payload.username, payload.password)
    tokens = _tokens(admin)
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post("/token", response_model=TokenOut, summary="OAuth2 password flow (form)")
@limiter.limit("10/minute")
async def login_form(
    request: Request,
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    admin = await _authenticate(session, form.username, form.password)
    tokens = _tokens(admin)
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    payload: RefreshIn = Body(default_factory=RefreshIn),
    refresh_token_cookie: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    """Accept the refresh token from an httpOnly cookie (preferred) or the
    request body (backward-compatible for API clients that manage tokens
    directly)."""
    token = refresh_token_cookie or payload.refresh_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing refresh token",
        )
    claims = decode_token(token)
    if claims is None or claims.token_type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid refresh token",
        )
    result = await session.execute(
        select(Admin).where(Admin.id == claims.admin_id, Admin.disabled_at.is_(None))
    )
    admin = result.scalar_one_or_none()
    if admin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin not found")
    tokens = _tokens(admin)
    # Rotate the refresh cookie on each successful refresh.
    _set_refresh_cookie(response, tokens.refresh_token)
    return tokens


@router.post("/logout", status_code=204)
async def logout(response: Response) -> None:
    """Clear the httpOnly refresh token cookie so the browser discards the
    session even if the access token has not yet expired."""
    _clear_refresh_cookie(response)


@router.get("/me", response_model=AdminOut)
async def me(admin: Admin = Depends(get_current_admin)) -> Admin:
    return admin
