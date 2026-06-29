"""Tests for per-tenant config overrides and effective() fallback logic."""

from __future__ import annotations

from unittest.mock import Mock, patch

from shared.tenant import effective


class TestEffective:
    """The effective() helper resolves config values: tenant override → global setting."""

    def test_returns_global_when_tenant_none(self):
        """When tenant is None, always return the global setting."""
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.dedupe_lookback_days = 7
            result = effective("dedupe_lookback_days", tenant=None)
            assert result == 7

    def test_returns_tenant_override_when_set(self):
        """When tenant has a non-None value, prefer it over global."""
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.dedupe_lookback_days = 7
            tenant = Mock()
            tenant.dedupe_lookback_days = 3
            result = effective("dedupe_lookback_days", tenant)
            assert result == 3

    def test_falls_back_to_global_when_tenant_field_null(self):
        """When tenant field is None, fall back to global setting."""
        with patch("shared.tenant.get_settings") as mock:
            mock.return_value.publish_spacing_seconds = 2.0
            tenant = Mock()
            tenant.publish_spacing_seconds = None
            result = effective("publish_spacing_seconds", tenant)
            assert result == 2.0

    def test_works_for_all_override_fields(self):
        """Verify effective() works for all six per-tenant config fields."""
        with patch("shared.tenant.get_settings") as mock:
            settings = mock.return_value
            settings.ai_model = "gpt-4"
            settings.ai_max_tokens = 4000
            settings.ai_timeout_seconds = 30
            settings.dedupe_lookback_days = 7
            settings.publish_spacing_seconds = 2.0
            settings.media_max_size_bytes = 2147483648

            tenant = Mock()
            tenant.ai_model = "claude-opus-4"
            tenant.ai_max_tokens = None  # fallback
            tenant.ai_timeout_seconds = 60
            tenant.dedupe_lookback_days = None  # fallback
            tenant.publish_spacing_seconds = 5.0
            tenant.media_max_size_bytes = None  # fallback

            assert effective("ai_model", tenant) == "claude-opus-4"
            assert effective("ai_max_tokens", tenant) == 4000
            assert effective("ai_timeout_seconds", tenant) == 60
            assert effective("dedupe_lookback_days", tenant) == 7
            assert effective("publish_spacing_seconds", tenant) == 5.0
            assert effective("media_max_size_bytes", tenant) == 2147483648
