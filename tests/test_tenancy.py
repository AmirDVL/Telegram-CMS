"""Tests for tenant scoping helpers (shared/tenant.py)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, String, select
from sqlalchemy.orm import Mapped, mapped_column

from shared.tenant import is_multi_tenant, scope_query, stamp_tenant


# ── is_multi_tenant() ──────────────────────────────────────────────────────


class TestIsMultiTenant:
    def test_returns_false_by_default(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = False
            assert is_multi_tenant() is False

    def test_returns_true_when_enabled(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = True
            assert is_multi_tenant() is True


# ── scope_query() ─────────────────────────────────────────────────────────


class _FakeModel:
    """Minimal stand-in with a tenant_id column attribute for query tests."""

    tenant_id = "tenant_id_col"


class TestScopeQuery:
    def test_noop_when_mt_disabled(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = False
            stmt = "original_stmt"
            result = scope_query(stmt, _FakeModel, tenant_id=42)
            assert result == "original_stmt"

    def test_noop_when_tenant_id_none(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = True
            stmt = "original_stmt"
            result = scope_query(stmt, _FakeModel, tenant_id=None)
            assert result == "original_stmt"

    def test_adds_where_clause_when_enabled(self):
        """When MT is on and tenant_id is set, the stmt should be mutated
        (not the same object as the input)."""
        from shared.models import Base, Post

        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = True
            original = select(Post)
            scoped = scope_query(original, Post, tenant_id=1)
            # The scoped query should have a WHERE clause, making it different
            # from the original.
            assert str(scoped) != str(original)
            assert "tenant_id" in str(scoped)


# ── stamp_tenant() ─────────────────────────────────────────────────────────


class _StampTarget:
    tenant_id = None


class TestStampTenant:
    def test_noop_when_mt_disabled(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = False
            obj = _StampTarget()
            stamp_tenant(obj, tenant_id=42)
            assert obj.tenant_id is None

    def test_noop_when_tenant_id_none(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = True
            obj = _StampTarget()
            stamp_tenant(obj, tenant_id=None)
            assert obj.tenant_id is None

    def test_sets_tenant_id_when_enabled(self):
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.multi_tenancy_enabled = True
            obj = _StampTarget()
            stamp_tenant(obj, tenant_id=7)
            assert obj.tenant_id == 7
