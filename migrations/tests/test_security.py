from shared.enums import Role
from shared.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify():
    h = hash_password("s3cret-pass")
    assert h != "s3cret-pass"
    assert verify_password("s3cret-pass", h) is True
    assert verify_password("wrong", h) is False


def test_access_token_roundtrip():
    token = create_access_token(42, "alice", Role.admin)
    claims = decode_token(token)
    assert claims is not None
    assert claims.admin_id == 42
    assert claims.sub == "alice"
    assert claims.role == Role.admin
    assert claims.token_type == "access"


def test_refresh_token_type():
    token = create_refresh_token(1, "bob", Role.editor)
    claims = decode_token(token)
    assert claims is not None
    assert claims.token_type == "refresh"


def test_decode_invalid_token_returns_none():
    assert decode_token("not-a-jwt") is None
