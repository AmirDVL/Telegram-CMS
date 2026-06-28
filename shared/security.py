"""Password hashing (argon2) + JWT issuance/verification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import argon2
import jwt
from argon2.exceptions import VerifyMismatchError

from shared.config import get_settings
from shared.enums import Role

_ph = argon2.PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except argon2.exceptions.InvalidHashError:
        return False


def needs_rehash(password_hash: str) -> bool:
    return _ph.check_needs_rehash(password_hash)


@dataclass(slots=True)
class TokenClaims:
    sub: str  # username
    admin_id: int
    role: Role
    token_type: str  # "access" | "refresh"
    exp: datetime


def _encode(payload: dict) -> str:
    s = get_settings()
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algo)


def _decode(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algo])


def create_access_token(admin_id: int, username: str, role: Role) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.access_token_ttl_minutes)
    return _encode(
        {
            "sub": username,
            "admin_id": admin_id,
            "role": role.value,
            "token_type": "access",
            "iat": now,
            "exp": exp,
        }
    )


def create_refresh_token(admin_id: int, username: str, role: Role) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(days=s.refresh_token_ttl_days)
    return _encode(
        {
            "sub": username,
            "admin_id": admin_id,
            "role": role.value,
            "token_type": "refresh",
            "iat": now,
            "exp": exp,
        }
    )


def decode_token(token: str) -> TokenClaims | None:
    try:
        data = _decode(token)
    except jwt.PyJWTError:
        return None
    return TokenClaims(
        sub=data["sub"],
        admin_id=int(data["admin_id"]),
        role=Role(data["role"]),
        token_type=data["token_type"],
        exp=datetime.fromtimestamp(data["exp"], tz=UTC),
    )
