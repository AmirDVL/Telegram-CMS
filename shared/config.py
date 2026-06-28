"""Application settings (pydantic-settings). Read once and cached."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_TWO_GB = 2 * 1024 * 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="ignore")

    # ── Postgres ──────────────────────────────────────────────────────────
    # The full DSN is the single source of truth for the database URL,
    # including the password.  The bare POSTGRES_PASSWORD env var is only
    # consumed by docker-compose to configure the Postgres service itself;
    # do not duplicate it here to avoid silent divergence.
    postgres_dsn: str = "postgresql+asyncpg://cms:cms@postgres:5432/cms"

    # ── Redis / ARQ ───────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379/0"

    # ── Auth (web back-office) ────────────────────────────────────────────
    # Empty by default — the API fails fast on startup if unset/insecure.
    jwt_secret: str = ""
    jwt_algo: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14
    seed_admin_username: str = "admin"
    seed_admin_password: str = ""

    # ── Policies / retention (plan §9 defaults) ──────────────────────────
    dedupe_lookback_days: int = 7
    audit_retention_days: int = 90
    media_retention_days: int = 30
    max_concurrent_publishes: int = 1
    publish_spacing_seconds: float = 2.0
    media_max_size_default: int = _TWO_GB

    # ── Bot API bot (aiogram) + local Bot API server ──────────────────────
    bot_token: str = ""
    bot_api_server_url: str = "http://botapi:8081"
    bot_api_server_file_path: str = "/var/lib/telegram-bot-api"
    destination_channel_id: int = 0
    editor_group_id: int = 0

    # ── Userbot (Telethon MTProto) ────────────────────────────────────────
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_name: str = "cms_userbot"
    telegram_2fa_password: str = ""
    session_dir: str = "/data/sessions"
    media_dir: str = "/media"

    # ── Web / API ─────────────────────────────────────────────────────────
    api_base_url: str = "http://api:8000"
    web_base_url: str = "http://web:3000"
    cors_origins: str = "*"
    app_domain: str = "localhost"

    # ── Healthz ports (internal; probed by Docker healthchecks) ──────────
    bot_health_port: int = 8082
    worker_health_port: int = 8083
    userbot_health_port: int = 8084

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def public_web_url(self) -> str:
        scheme = "https" if self.app_domain not in ("localhost", "") else "http"
        host = self.app_domain or "localhost"
        return f"{scheme}://{host}"

    @property
    def auth_secret_valid(self) -> bool:
        """True only when a real JWT secret is configured (not empty/placeholder)."""
        return bool(self.jwt_secret) and not self.jwt_secret.startswith("change-this")

    def require_auth_secret(self) -> None:
        """Fail fast if the JWT secret is unset or the known placeholder."""
        if not self.auth_secret_valid:
            raise RuntimeError(
                "JWT_SECRET must be set to a strong random string (got empty/placeholder)."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Force a fresh read of settings (used by tests that mutate env)."""
    get_settings.cache_clear()
    return get_settings()
