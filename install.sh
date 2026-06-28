#!/usr/bin/env bash
# install.sh — tg-cms one-shot deployment installer
# Safe to run multiple times (idempotent).
#
# -E  : ERR trap is inherited by shell functions, so failures inside helpers
#       (e.g. wait_for_postgres) are caught too.
# -e  : abort on any unhandled non-zero command.
# -u  : abort on use of an unset variable.
# -o pipefail : a pipeline fails if any stage fails, not just the last.
set -Eeuo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
box()  { echo -e "${CYAN}${BOLD}$*${RESET}"; }

# Fail fast: if any command aborts the script (set -e), report where and remind
# the operator that re-running is safe. Commands that may legitimately fail are
# guarded with `|| true` and never reach this trap.
trap 'rc=$?; echo -e "${RED}[✗] Aborted at line ${LINENO} (exit ${rc}). The host may be partially configured; fix the error above and re-run — install.sh is idempotent.${RESET}" >&2' ERR

# Pin the Compose project name so volume names are deterministic
# (e.g. tg-cms_pgdata) regardless of the directory the script runs from. This
# also makes the tg-cms_* volume names in docs/RUNBOOK.md backup commands correct.
export COMPOSE_PROJECT_NAME=tg-cms

ask() {
    local prompt="$1" var="$2"
    local default="${3:-}"
    local display_default=""
    [[ -n "$default" ]] && display_default=" [${default}]"
    while true; do
        read -rp "$(echo -e "${BOLD}${prompt}${display_default}: ${RESET}")" value
        value="${value:-$default}"
        [[ -n "$value" ]] && { printf -v "$var" '%s' "$value"; return; }
        warn "Value is required."
    done
}

ask_secret() {
    local prompt="$1" var="$2"
    local default="${3:-}"
    local display_default=""
    [[ -n "$default" ]] && display_default=" [${default}]"
    while true; do
        read -rsp "$(echo -e "${BOLD}${prompt}${display_default}: ${RESET}")" value
        echo
        value="${value:-$default}"
        [[ -n "$value" ]] && { printf -v "$var" '%s' "$value"; return; }
        warn "Value is required."
    done
}

ask_optional() {
    local prompt="$1" var="$2"
    local default="${3:-}"
    local display_default=""
    [[ -n "$default" ]] && display_default=" [${default}]"
    read -rp "$(echo -e "${BOLD}${prompt}${display_default}: ${RESET}")" value
    value="${value:-$default}"
    printf -v "$var" '%s' "$value"
}

ask_optional_secret() {
    local prompt="$1" var="$2"
    read -rsp "$(echo -e "${BOLD}${prompt} (blank = none): ${RESET}")" value
    echo
    printf -v "$var" '%s' "$value"
}

ask_yn() {
    local prompt="$1"
    local default="${2:-N}"
    local yn_display="y/N"; [[ "$default" == "Y" || "$default" == "y" ]] && yn_display="Y/n"
    read -rp "$(echo -e "${BOLD}${prompt} [${yn_display}]: ${RESET}")" yn
    yn="${yn:-$default}"
    [[ "$yn" =~ ^[Yy]$ ]]
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Root check ─────────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || die "Please run as root: sudo bash install.sh"

# ── 2. OS & package manager detection ────────────────────────────────────────
log "Detecting OS and package manager..."
if command -v apt-get &>/dev/null; then
    PKG_MGR=apt
elif command -v dnf &>/dev/null; then
    PKG_MGR=dnf
elif command -v yum &>/dev/null; then
    PKG_MGR=yum
else
    die "Unsupported distro — install Docker manually, then re-run."
fi
log "Package manager: ${PKG_MGR}"

pkg_install() {
    case "$PKG_MGR" in
        apt) apt-get install -y "$@" ;;
        dnf) dnf install -y "$@"     ;;
        yum) yum install -y "$@"     ;;
    esac
}

pkg_installed() { command -v "$1" &>/dev/null; }

log "Ensuring base tools are present..."
NEEDED_TOOLS=()
pkg_installed curl    || NEEDED_TOOLS+=(curl)
pkg_installed openssl || NEEDED_TOOLS+=(openssl)
pkg_installed ss      || NEEDED_TOOLS+=(iproute2)

if [[ ${#NEEDED_TOOLS[@]} -gt 0 ]]; then
    [[ "$PKG_MGR" == "apt" ]] && apt-get update -qq
    pkg_install "${NEEDED_TOOLS[@]}"
fi

# ── 3. Docker & Docker Compose installation (idempotent) ─────────────────────
# "Already installed" requires BOTH the docker engine AND some compose flavour
# (v2 plugin `docker compose`, or legacy standalone `docker-compose`).
have_compose() { docker compose version &>/dev/null || command -v docker-compose &>/dev/null; }

if docker version &>/dev/null && have_compose; then
    log "Docker and Docker Compose are already installed — skipping."
else
    log "Installing Docker..."
    case "$PKG_MGR" in
        apt)
            curl -fsSL https://get.docker.com | sh
            ;;
        dnf)
            dnf config-manager --add-repo \
                https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true
            pkg_install docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
        yum)
            yum-config-manager --add-repo \
                https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true
            pkg_install docker-ce docker-ce-cli containerd.io docker-compose-plugin
            ;;
    esac
fi

log "Enabling and starting Docker service..."
systemctl enable --now docker

# ── 3b. Resolve the Compose command (v2 plugin vs legacy v1 standalone) ──────
# Older client hosts ship only the standalone `docker-compose` binary; modern
# hosts use the integrated `docker compose` plugin. Resolve once into a wrapper
# function `dc` (used throughout) and an absolute `DC_EXEC` (for the systemd unit).
DOCKER_BIN="$(command -v docker || true)"
if docker compose version &>/dev/null; then
    dc() { docker compose "$@"; }
    DC_EXEC="${DOCKER_BIN} compose"   # absolute form for the systemd unit
    DC_HINT="docker compose"          # friendly form for printed instructions
elif command -v docker-compose &>/dev/null; then
    dc() { docker-compose "$@"; }
    DC_EXEC="$(command -v docker-compose)"
    DC_HINT="docker-compose"
else
    die "Neither 'docker compose' (v2 plugin) nor 'docker-compose' (v1) is available."
fi
log "Using compose command: ${DC_EXEC}"

# ── 4. Docker proxy / registry mirror configuration ───────────────────────────
DOCKER_RELOAD_NEEDED=false

echo
box "━━━ Docker network configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ask_yn "Configure HTTP proxy for the Docker daemon? (Use in restricted networks)"; then
    ask         "  HTTP_PROXY  (e.g. http://proxy.corp:3128)"  PROXY_HTTP
    ask         "  HTTPS_PROXY (e.g. http://proxy.corp:3128)"  PROXY_HTTPS
    ask_optional "  NO_PROXY    (e.g. localhost,127.0.0.1)"    PROXY_NO "localhost,127.0.0.1"

    PROXY_DIR="/etc/systemd/system/docker.service.d"
    PROXY_FILE="${PROXY_DIR}/http-proxy.conf"
    PROXY_CONTENT="[Service]
Environment=\"HTTP_PROXY=${PROXY_HTTP}\"
Environment=\"HTTPS_PROXY=${PROXY_HTTPS}\"
Environment=\"NO_PROXY=${PROXY_NO}\""

    mkdir -p "$PROXY_DIR"
    if [[ -f "$PROXY_FILE" ]] && [[ "$(cat "$PROXY_FILE")" == "$PROXY_CONTENT" ]]; then
        log "Docker proxy config unchanged — skipping."
    else
        echo "$PROXY_CONTENT" > "$PROXY_FILE"
        log "Docker proxy config written to ${PROXY_FILE}"
        DOCKER_RELOAD_NEEDED=true
    fi
fi

if ask_yn "Configure local registry mirrors? (Use when Docker Hub is blocked)"; then
    ask_optional "  Mirror URLs (space-separated, e.g. https://mirror.gcr.io)" MIRROR_INPUT ""
    DAEMON_JSON="/etc/docker/daemon.json"
    # Build a JSON array from the space-separated input
    MIRRORS_JSON="["
    first=true
    for url in $MIRROR_INPUT; do
        [[ "$first" == true ]] && first=false || MIRRORS_JSON+=","
        MIRRORS_JSON+="\"${url}\""
    done
    MIRRORS_JSON+="]"

    DAEMON_CONTENT="{\"registry-mirrors\": ${MIRRORS_JSON}}"
    if [[ -f "$DAEMON_JSON" ]] && [[ "$(cat "$DAEMON_JSON")" == "$DAEMON_CONTENT" ]]; then
        log "Registry mirror config unchanged — skipping."
    else
        echo "$DAEMON_CONTENT" > "$DAEMON_JSON"
        log "Registry mirrors written to ${DAEMON_JSON}"
        DOCKER_RELOAD_NEEDED=true
    fi
fi

if [[ "$DOCKER_RELOAD_NEEDED" == true ]]; then
    log "Reloading Docker daemon to apply network configuration..."
    systemctl daemon-reload
    systemctl restart docker
fi

# ── 5. Existing-install detection (DB-lockout guard) ─────────────────────────
# Postgres bakes its credentials into the data volume on FIRST init only. If a
# pgdata volume already exists, regenerating POSTGRES_PASSWORD would lock the
# stack out of its own database forever. Detect the pre-existing install via the
# (now deterministic) volume name so we can preserve the DB password.
PGDATA_VOLUME="${COMPOSE_PROJECT_NAME}_pgdata"
EXISTING_INSTALL=false
if docker volume inspect "$PGDATA_VOLUME" &>/dev/null; then
    EXISTING_INSTALL=true
    log "Existing data volume '${PGDATA_VOLUME}' detected — preserving database credentials."
fi

# ── 6. Secret generation ──────────────────────────────────────────────────────
gen_secret() { openssl rand -hex 32; }

ENV_FILE="${SCRIPT_DIR}/.env"
REGENERATE_SECRETS=true
declare -A EXISTING_ENV=()

if [[ -f "$ENV_FILE" ]]; then
    echo
    warn ".env already exists at ${ENV_FILE}"
    if ask_yn "Re-generate secrets and overwrite .env?"; then
        REGENERATE_SECRETS=true
    else
        REGENERATE_SECRETS=false
        log "Loading existing .env values..."
        while IFS='=' read -r key value; do
            [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
            # strip surrounding quotes if any
            value="${value%\"}"
            value="${value#\"}"
            EXISTING_ENV["$key"]="$value"
        done < <(grep -v '^\s*#' "$ENV_FILE" | grep '=')
    fi
elif [[ "$EXISTING_INSTALL" == true ]]; then
    # Volume exists but the .env holding its password is gone — we cannot recover
    # the password Postgres was initialized with. Refuse rather than generate a
    # mismatched one and silently lock the stack out of its database.
    die "Data volume '${PGDATA_VOLUME}' exists but .env is missing.
    The database password cannot be recovered from the volume. Either:
      • restore the original .env next to install.sh, or
      • destroy the database to start fresh:  docker volume rm ${PGDATA_VOLUME}"
fi

get_existing() {
    local key="$1" default="${2:-}"
    echo "${EXISTING_ENV[$key]:-$default}"
}

if [[ "$REGENERATE_SECRETS" == true ]]; then
    JWT_SECRET=$(gen_secret)
    SEED_ADMIN_PASSWORD=$(gen_secret)
    GRAFANA_ADMIN_PASSWORD=$(gen_secret)
    REDIS_PASSWORD=$(gen_secret)
    # Never rotate the Postgres password against an initialized volume.
    if [[ "$EXISTING_INSTALL" == true ]]; then
        POSTGRES_PASSWORD=$(get_existing POSTGRES_PASSWORD "")
        [[ -n "$POSTGRES_PASSWORD" ]] || die "Cannot preserve POSTGRES_PASSWORD (not found in .env) against existing volume ${PGDATA_VOLUME}."
        warn "Keeping existing POSTGRES_PASSWORD (data volume already initialized)."
    else
        POSTGRES_PASSWORD=$(gen_secret)
    fi
    log "Secrets generated."
else
    POSTGRES_PASSWORD=$(get_existing POSTGRES_PASSWORD "$(gen_secret)")
    JWT_SECRET=$(get_existing JWT_SECRET "$(gen_secret)")
    SEED_ADMIN_PASSWORD=$(get_existing SEED_ADMIN_PASSWORD "$(gen_secret)")
    GRAFANA_ADMIN_PASSWORD=$(get_existing GRAFANA_ADMIN_PASSWORD "$(gen_secret)")
    REDIS_PASSWORD=$(get_existing REDIS_PASSWORD "$(gen_secret)")
    log "Using secrets from existing .env."
fi

# ── 7. Interactive prompts for required user-supplied values ──────────────────
echo
box "━━━ Telegram configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Get API ID/Hash from https://my.telegram.org → API development tools"
echo

TG_API_ID=$(get_existing TELEGRAM_API_ID "")
TG_API_HASH=$(get_existing TELEGRAM_API_HASH "")
BOT_TOKEN=$(get_existing BOT_TOKEN "")
DEST_CHANNEL=$(get_existing DESTINATION_CHANNEL_ID "")
EDITOR_GROUP=$(get_existing EDITOR_GROUP_ID "")

[[ -z "$TG_API_ID" || "$TG_API_ID" == "0" ]] && \
    ask "  Telegram API ID" TG_API_ID

[[ -z "$TG_API_HASH" || "$TG_API_HASH" == "changeme" ]] && \
    ask_secret "  Telegram API Hash" TG_API_HASH

[[ -z "$BOT_TOKEN" || "$BOT_TOKEN" == "123456:changeme" ]] && \
    ask_secret "  Bot Token (from @BotFather)" BOT_TOKEN

[[ -z "$DEST_CHANNEL" || "$DEST_CHANNEL" == "-1000000000000" ]] && \
    ask "  Destination Channel ID (negative number, e.g. -1001234567890)" DEST_CHANNEL

[[ -z "$EDITOR_GROUP" || "$EDITOR_GROUP" == "-1000000000001" ]] && \
    ask "  Editor Supergroup ID (negative number, e.g. -1009876543210)" EDITOR_GROUP

TG_2FA=$(get_existing TELEGRAM_2FA_PASSWORD "")
[[ -z "$TG_2FA" ]] && \
    ask_optional_secret "  Userbot 2FA password" TG_2FA

echo
box "━━━ Web / domain configuration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

APP_DOMAIN=$(get_existing APP_DOMAIN "")
[[ -z "$APP_DOMAIN" || "$APP_DOMAIN" == "cms.example.com" ]] && \
    ask "  Public domain (e.g. cms.example.com)" APP_DOMAIN

echo
box "━━━ AI Transformation (optional) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

AI_ENABLED_DEFAULT=$(get_existing AI_ENABLED "false")
AI_ENABLED="false"
if ask_yn "  Enable AI text transformation?"; then
    AI_ENABLED="true"
    ask_optional  "  Provider URL" AI_PROVIDER_URL \
        "$(get_existing AI_PROVIDER_URL 'https://api.openai.com/v1')"
    ask_optional_secret "  API key" AI_API_KEY
    ask_optional  "  Model"        AI_MODEL \
        "$(get_existing AI_MODEL 'gpt-4o-mini')"
else
    AI_PROVIDER_URL=$(get_existing AI_PROVIDER_URL "https://api.openai.com/v1")
    AI_API_KEY=$(get_existing AI_API_KEY "")
    AI_MODEL=$(get_existing AI_MODEL "gpt-4o-mini")
fi

# ── 8. Write .env ─────────────────────────────────────────────────────────────
if [[ "$REGENERATE_SECRETS" == true ]]; then
    POSTGRES_DSN="postgresql+asyncpg://cms:${POSTGRES_PASSWORD}@postgres:5432/cms"
    REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"

    log "Writing .env..."
    cat > "$ENV_FILE" <<EOF
# Generated by install.sh — do not edit secrets manually; re-run install.sh to rotate.

# ── Compose ───────────────────────────────────────────────────────────────────
# Pins volume/network names to tg-cms_* (read by docker compose from this file).
COMPOSE_PROJECT_NAME=tg-cms

# ── Telegram (userbot / MTProto) ──────────────────────────────────────────────
TELEGRAM_API_ID=${TG_API_ID}
TELEGRAM_API_HASH=${TG_API_HASH}
TELEGRAM_SESSION_NAME=cms_userbot
TELEGRAM_2FA_PASSWORD=${TG_2FA}
SESSION_DIR=/data/sessions
MEDIA_DIR=/media

# ── Bot API bot (aiogram) ────────────────────────────────────────────────────
BOT_TOKEN=${BOT_TOKEN}
BOT_API_SERVER_URL=http://botapi:8081
BOT_API_SERVER_FILE_PATH=/var/lib/telegram-bot-api
DESTINATION_CHANNEL_ID=${DEST_CHANNEL}
EDITOR_GROUP_ID=${EDITOR_GROUP}

# ── Postgres ──────────────────────────────────────────────────────────────────
POSTGRES_DSN=${POSTGRES_DSN}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_URL=${REDIS_URL}
REDIS_PASSWORD=${REDIS_PASSWORD}

# ── Auth (web back-office) ───────────────────────────────────────────────────
JWT_SECRET=${JWT_SECRET}
JWT_ALGO=HS256
ACCESS_TOKEN_TTL_MINUTES=30
REFRESH_TOKEN_TTL_DAYS=14
SEED_ADMIN_USERNAME=admin
SEED_ADMIN_PASSWORD=${SEED_ADMIN_PASSWORD}

# ── Policies / retention ─────────────────────────────────────────────────────
DEDUPE_LOOKBACK_DAYS=7
AUDIT_RETENTION_DAYS=90
MEDIA_RETENTION_DAYS=30
MAX_CONCURRENT_PUBLISHES=1
PUBLISH_SPACING_SECONDS=2.0
MEDIA_MAX_SIZE_DEFAULT=2147483648

# ── Web / API ────────────────────────────────────────────────────────────────
API_BASE_URL=http://api:8000
WEB_BASE_URL=http://web:3000
CORS_ORIGINS=https://${APP_DOMAIN}
APP_DOMAIN=${APP_DOMAIN}

# ── Observability ─────────────────────────────────────────────────────────────
GRAFANA_ADMIN_PASSWORD=${GRAFANA_ADMIN_PASSWORD}

# ── Feature flags ─────────────────────────────────────────────────────────────
MULTI_TENANCY_ENABLED=false

# ── AI Transformation ─────────────────────────────────────────────────────────
AI_ENABLED=${AI_ENABLED}
AI_PROVIDER_URL=${AI_PROVIDER_URL}
AI_API_KEY=${AI_API_KEY}
AI_MODEL=${AI_MODEL}
AI_MAX_TOKENS=2048
AI_TIMEOUT_SECONDS=30
EOF
    chmod 600 "$ENV_FILE"
    log ".env written and locked to root-only (600)."
else
    log "Skipping .env overwrite (existing file kept)."
    # Ensure a preserved .env from an older install still pins the project name,
    # otherwise compose would derive a different (directory-based) volume prefix.
    if ! grep -q '^COMPOSE_PROJECT_NAME=' "$ENV_FILE"; then
        printf '\n# Added by install.sh — pins volume/network names to tg-cms_*\nCOMPOSE_PROJECT_NAME=tg-cms\n' >> "$ENV_FILE"
        log "Added COMPOSE_PROJECT_NAME=tg-cms to existing .env."
    fi
fi

# ── 9. Port conflict detection ────────────────────────────────────────────────
echo
box "━━━ Port availability check ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

OVERRIDE_FILE="${SCRIPT_DIR}/docker-compose.override.yml"

port_in_use() { ss -tlnp 2>/dev/null | grep -q ":${1} "; }

resolve_port() {
    local name="$1" default="$2" var="$3"
    if port_in_use "$default"; then
        warn "Port ${default} (${name}) is already in use."
        ask_optional "  Remap ${name} host port to?" "$var" "$((default + 1000))"
    else
        printf -v "$var" '%s' "$default"
        log "Port ${default} (${name}) is free."
    fi
}

# Echo the host port previously mapped to container port $2 in override file $1.
extract_host_port() {
    grep -oE "\"[0-9]+:$2\"" "$1" 2>/dev/null | head -1 | tr -d '"' | cut -d: -f1 || true
}

if [[ -f "$OVERRIDE_FILE" ]]; then
    # Re-run: reuse the existing mapping. Re-detecting here would flag our OWN
    # running Caddy/Grafana as conflicts and prompt to remap on every run.
    HOST_HTTP_PORT=$(extract_host_port "$OVERRIDE_FILE" 80);   HOST_HTTP_PORT=${HOST_HTTP_PORT:-80}
    HOST_HTTPS_PORT=$(extract_host_port "$OVERRIDE_FILE" 443); HOST_HTTPS_PORT=${HOST_HTTPS_PORT:-443}
    HOST_GRAFANA_PORT=$(extract_host_port "$OVERRIDE_FILE" 3000); HOST_GRAFANA_PORT=${HOST_GRAFANA_PORT:-3001}
    log "Reusing existing port mapping (HTTP=${HOST_HTTP_PORT}, HTTPS=${HOST_HTTPS_PORT}, Grafana=${HOST_GRAFANA_PORT})."
else
    resolve_port "HTTP (Caddy)"    80   HOST_HTTP_PORT
    resolve_port "HTTPS (Caddy)"   443  HOST_HTTPS_PORT
    resolve_port "Grafana"         3001 HOST_GRAFANA_PORT
fi

# ── 10. Write docker-compose.override.yml ────────────────────────────────────
log "Writing docker-compose.override.yml..."

# Build port sections only if they were remapped
CADDY_PORTS_BLOCK=""
if [[ "$HOST_HTTP_PORT" != "80" || "$HOST_HTTPS_PORT" != "443" ]]; then
    CADDY_PORTS_BLOCK="    ports:
      - \"${HOST_HTTP_PORT}:80\"
      - \"${HOST_HTTPS_PORT}:443\""
fi

GRAFANA_PORTS_BLOCK=""
if [[ "$HOST_GRAFANA_PORT" != "3001" ]]; then
    GRAFANA_PORTS_BLOCK="    ports:
      - \"${HOST_GRAFANA_PORT}:3000\""
fi

# Write the override — Redis requirepass is always included
{
    echo "# Generated by install.sh"
    echo "services:"
    echo "  redis:"
    echo "    command: [\"redis-server\", \"--appendonly\", \"yes\", \"--requirepass\", \"${REDIS_PASSWORD}\"]"
    if [[ -n "$CADDY_PORTS_BLOCK" ]]; then
        echo "  caddy:"
        echo "$CADDY_PORTS_BLOCK"
    fi
    if [[ -n "$GRAFANA_PORTS_BLOCK" ]]; then
        echo "  grafana:"
        echo "$GRAFANA_PORTS_BLOCK"
    fi
} > "$OVERRIDE_FILE"

log "docker-compose.override.yml written."

# ── 11. Docker Compose bring-up ───────────────────────────────────────────────
echo
box "━━━ Bringing up the stack ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$SCRIPT_DIR"

# Only Postgres (and Redis) are needed before migrations; botapi/web/caddy come
# up with the full `dc up -d` below. This avoids blocking on slower images.
log "Starting database + queue (postgres, redis)..."
dc up -d postgres redis

# Gate migrations on Postgres actually accepting connections. Runs pg_isready
# INSIDE the postgres container, so the host needs no postgres client or python3.
wait_for_postgres() {
    local tries=0 max=60
    log "Waiting for Postgres to accept connections..."
    until dc exec -T postgres pg_isready -U cms -d cms &>/dev/null; do
        tries=$((tries + 1))
        [[ $tries -ge $max ]] && die "Postgres not ready after $((max * 2))s — check 'dc logs postgres'."
        sleep 2
    done
    log "Postgres is ready."
}
wait_for_postgres

# `migrate` applies Alembic migrations to head AND seeds the super-admin + default
# tags/template (api/cli.py → _run_migrations + _seed_all). Both are idempotent,
# so re-running the installer is safe.
log "Running migrations + seeding (idempotent)..."
dc run --rm api python -m api.cli migrate

log "Starting all services..."
dc up -d

# ── 12. Systemd service ───────────────────────────────────────────────────────
echo
box "━━━ Systemd integration ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

UNIT_FILE="/etc/systemd/system/tg-cms.service"
UNIT_CONTENT="[Unit]
Description=Telegram CMS Bot (Docker Compose)
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${DC_EXEC} up -d --remove-orphans
ExecStop=${DC_EXEC} down
TimeoutStartSec=300
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target"

if [[ -f "$UNIT_FILE" ]] && [[ "$(cat "$UNIT_FILE")" == "$UNIT_CONTENT" ]]; then
    log "Systemd unit unchanged — skipping daemon-reload."
else
    echo "$UNIT_CONTENT" > "$UNIT_FILE"
    systemctl daemon-reload
    log "Systemd unit written to ${UNIT_FILE}"
fi

systemctl enable tg-cms
log "tg-cms.service enabled (will start automatically on boot)."

# ── 12.5. Zero-touch fleet auto-updates (opt-in) ─────────────────────────────
echo
box "━━━ Fleet auto-updates (optional) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

FLEET_UPDATES_ENABLED=false
if ask_yn "Enable automatic zero-touch updates? (pulls and rebuilds on every new commit)"; then
    FLEET_UPDATES_ENABLED=true

    # ── Fleet role ────────────────────────────────────────────────────────────
    echo
    echo "  Fleet role:"
    echo "    canary     — tracks origin/main; promotes stable on health-pass."
    echo "    production — tracks origin/stable (canary-verified commits only)."
    echo
    ask_optional "  Role" FLEET_ROLE "production"
    if [[ "$FLEET_ROLE" != "canary" && "$FLEET_ROLE" != "production" ]]; then
        warn "Unknown role '${FLEET_ROLE}' — defaulting to production."
        FLEET_ROLE=production
    fi

    if [[ "$FLEET_ROLE" == "canary" ]]; then
        FLEET_TRACK_REF="origin/main"
        log "Canary host: will track origin/main and promote stable on health-pass."
        echo
        warn "One-time operator step (if not done): create the 'stable' branch on the"
        warn "remote so production hosts have a ref to track:"
        warn "  git push origin main:stable"
        echo
        # Promotion token is optional; without it the operator/CI promotes manually.
        ask_optional_secret \
            "  GitHub push token for stable promotion (blank = use CI/operator)" \
            FLEET_PROMOTE_TOKEN
        if [[ -n "$FLEET_PROMOTE_TOKEN" ]]; then
            FLEET_PROMOTE_REMOTE="origin"
        else
            FLEET_PROMOTE_REMOTE=""
            log "No push token — stable will be advanced by CI/operator after canary is healthy."
        fi
    else
        FLEET_TRACK_REF="origin/stable"
        FLEET_PROMOTE_REMOTE=""
        FLEET_PROMOTE_TOKEN=""
        log "Production host: will track origin/stable (canary-verified commits only)."
    fi

    # ── Optional Telegram alerts ──────────────────────────────────────────────
    echo
    ask_optional "  Alert chat ID for update/rollback notifications (blank = none)" \
        FLEET_ALERT_CHAT_ID ""

    # ── Write /etc/tg-cms/fleet.conf (mode 600 — may hold a push token) ──────
    FLEET_CONF_DIR="/etc/tg-cms"
    FLEET_CONF_FILE="${FLEET_CONF_DIR}/fleet.conf"
    mkdir -p "$FLEET_CONF_DIR"

    FLEET_CONF_CONTENT="# /etc/tg-cms/fleet.conf — written by install.sh on $(date -u '+%Y-%m-%dT%H:%M:%SZ')
# Treat as a secret (mode 600): may contain a push token.
INSTALL_DIR=\"${SCRIPT_DIR}\"
DC_EXEC=\"${DC_EXEC}\"
FLEET_ROLE=${FLEET_ROLE}
FLEET_TRACK_REF=${FLEET_TRACK_REF}
HEALTH_TIMEOUT=180"

    [[ -n "$FLEET_PROMOTE_REMOTE" ]] && \
        FLEET_CONF_CONTENT+="
FLEET_PROMOTE_REMOTE=${FLEET_PROMOTE_REMOTE}"

    [[ -n "${FLEET_PROMOTE_TOKEN:-}" ]] && \
        FLEET_CONF_CONTENT+="
FLEET_PROMOTE_TOKEN=${FLEET_PROMOTE_TOKEN}"

    [[ -n "${FLEET_ALERT_CHAT_ID:-}" ]] && \
        FLEET_CONF_CONTENT+="
FLEET_ALERT_CHAT_ID=${FLEET_ALERT_CHAT_ID}
BOT_TOKEN=${BOT_TOKEN}"

    if [[ -f "$FLEET_CONF_FILE" ]] && [[ "$(cat "$FLEET_CONF_FILE")" == "$FLEET_CONF_CONTENT" ]]; then
        log "Fleet config unchanged — skipping."
    else
        echo "$FLEET_CONF_CONTENT" > "$FLEET_CONF_FILE"
        chmod 600 "$FLEET_CONF_FILE"
        log "Fleet config written to ${FLEET_CONF_FILE} (mode 600)."
    fi

    # ── Make updater scripts executable ───────────────────────────────────────
    chmod +x "${SCRIPT_DIR}/fleet/auto-update.sh"
    chmod +x "${SCRIPT_DIR}/fleet/health-gate.sh"
    log "fleet/auto-update.sh and fleet/health-gate.sh marked executable."

    # ── Write systemd service unit (compare-before-write, same pattern as §12) ─
    UPDATE_SVC_FILE="/etc/systemd/system/tg-cms-update.service"
    UPDATE_SVC_CONTENT="[Unit]
Description=tg-cms zero-touch fleet updater
Documentation=https://github.com/AmirDVL/glm-testing/blob/main/docs/FLEET_UPDATES.md
Requires=docker.service
After=docker.service network-online.target

[Service]
Type=oneshot
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${SCRIPT_DIR}/fleet/auto-update.sh
StandardOutput=journal
StandardError=journal
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target"

    SYSTEMD_RELOAD_NEEDED=false
    if [[ -f "$UPDATE_SVC_FILE" ]] && [[ "$(cat "$UPDATE_SVC_FILE")" == "$UPDATE_SVC_CONTENT" ]]; then
        log "tg-cms-update.service unchanged — skipping."
    else
        echo "$UPDATE_SVC_CONTENT" > "$UPDATE_SVC_FILE"
        SYSTEMD_RELOAD_NEEDED=true
        log "tg-cms-update.service written to ${UPDATE_SVC_FILE}"
    fi

    # ── Write systemd timer unit (compare-before-write) ───────────────────────
    UPDATE_TIMER_FILE="/etc/systemd/system/tg-cms-update.timer"
    UPDATE_TIMER_CONTENT="[Unit]
Description=Run tg-cms fleet updater every 5 minutes
Documentation=https://github.com/AmirDVL/glm-testing/blob/main/docs/FLEET_UPDATES.md

[Timer]
OnUnitActiveSec=5min
OnBootSec=5min
RandomizedDelaySec=120
Persistent=true

[Install]
WantedBy=timers.target"

    if [[ -f "$UPDATE_TIMER_FILE" ]] && [[ "$(cat "$UPDATE_TIMER_FILE")" == "$UPDATE_TIMER_CONTENT" ]]; then
        log "tg-cms-update.timer unchanged — skipping."
    else
        echo "$UPDATE_TIMER_CONTENT" > "$UPDATE_TIMER_FILE"
        SYSTEMD_RELOAD_NEEDED=true
        log "tg-cms-update.timer written to ${UPDATE_TIMER_FILE}"
    fi

    if [[ "$SYSTEMD_RELOAD_NEEDED" == true ]]; then
        systemctl daemon-reload
        log "systemd daemon reloaded."
    fi

    systemctl enable --now tg-cms-update.timer
    log "tg-cms-update.timer enabled and started."
fi

# ── 13. Post-install summary ──────────────────────────────────────────────────
echo
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
box "  tg-cms installed successfully"
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"; HOST_IP="${HOST_IP:-<host-ip>}"
echo -e "  Web back-office : ${CYAN}https://${APP_DOMAIN}${RESET}"
echo -e "  API docs        : ${CYAN}https://${APP_DOMAIN}/api/docs${RESET}"
echo -e "  Grafana         : ${CYAN}http://${HOST_IP}:${HOST_GRAFANA_PORT}${RESET}"
echo -e "  Admin login     : ${BOLD}admin${RESET} / ${BOLD}${SEED_ADMIN_PASSWORD}${RESET}"
echo
echo -e "${YELLOW}${BOLD}  ⚠  REQUIRED NEXT STEP — Userbot first-run login (interactive):${RESET}"
echo
echo -e "     ${BOLD}${DC_HINT} run --rm -it userbot python -m userbot.login${RESET}"
echo -e "     (Enter phone number → verification code → 2FA password if set)"
echo -e "     Then: ${BOLD}${DC_HINT} restart userbot${RESET}"
echo
echo -e "  Manage the stack:"
echo -e "     ${BOLD}sudo systemctl {start|stop|restart|status} tg-cms${RESET}"
echo -e "     ${BOLD}${DC_HINT} logs -f${RESET}"
echo
if [[ "$FLEET_UPDATES_ENABLED" == true ]]; then
    echo -e "  Auto-updates   : ${GREEN}enabled${RESET} (role: ${BOLD}${FLEET_ROLE}${RESET}, tracking ${BOLD}${FLEET_TRACK_REF}${RESET})"
    echo -e "     Pause  : ${BOLD}sudo systemctl disable --now tg-cms-update.timer${RESET}"
    echo -e "     Force  : ${BOLD}sudo systemctl start tg-cms-update.service${RESET}"
    echo -e "     Logs   : ${BOLD}journalctl -u tg-cms-update -f${RESET}"
    echo -e "     See also: ${CYAN}docs/FLEET_UPDATES.md${RESET}"
else
    echo -e "  Auto-updates   : ${YELLOW}disabled${RESET} (re-run install.sh to enable)"
fi
echo
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
