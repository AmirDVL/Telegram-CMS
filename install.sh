#!/usr/bin/env bash
# install.sh — tg-cms one-shot deployment installer
# Safe to run multiple times (idempotent).
set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }
box()  { echo -e "${CYAN}${BOLD}$*${RESET}"; }

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
DOCKER_ALREADY_OK=false
if docker version &>/dev/null && docker compose version &>/dev/null 2>&1; then
    log "Docker and Docker Compose are already installed — skipping."
    DOCKER_ALREADY_OK=true
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

# ── 5. Secret generation ──────────────────────────────────────────────────────
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
fi

get_existing() {
    local key="$1" default="${2:-}"
    echo "${EXISTING_ENV[$key]:-$default}"
}

if [[ "$REGENERATE_SECRETS" == true ]]; then
    POSTGRES_PASSWORD=$(gen_secret)
    JWT_SECRET=$(gen_secret)
    SEED_ADMIN_PASSWORD=$(gen_secret)
    GRAFANA_ADMIN_PASSWORD=$(gen_secret)
    REDIS_PASSWORD=$(gen_secret)
    log "Secrets generated."
else
    POSTGRES_PASSWORD=$(get_existing POSTGRES_PASSWORD "$(gen_secret)")
    JWT_SECRET=$(get_existing JWT_SECRET "$(gen_secret)")
    SEED_ADMIN_PASSWORD=$(get_existing SEED_ADMIN_PASSWORD "$(gen_secret)")
    GRAFANA_ADMIN_PASSWORD=$(get_existing GRAFANA_ADMIN_PASSWORD "$(gen_secret)")
    REDIS_PASSWORD=$(get_existing REDIS_PASSWORD "$(gen_secret)")
    log "Using secrets from existing .env."
fi

# ── 6. Interactive prompts for required user-supplied values ──────────────────
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

# ── 7. Write .env ─────────────────────────────────────────────────────────────
if [[ "$REGENERATE_SECRETS" == true ]]; then
    POSTGRES_DSN="postgresql+asyncpg://cms:${POSTGRES_PASSWORD}@postgres:5432/cms"
    REDIS_URL="redis://:${REDIS_PASSWORD}@redis:6379/0"

    log "Writing .env..."
    cat > "$ENV_FILE" <<EOF
# Generated by install.sh — do not edit secrets manually; re-run install.sh to rotate.

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
fi

# ── 8. Port conflict detection ────────────────────────────────────────────────
echo
box "━━━ Port availability check ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

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

resolve_port "HTTP (Caddy)"    80   HOST_HTTP_PORT
resolve_port "HTTPS (Caddy)"   443  HOST_HTTPS_PORT
resolve_port "Grafana"         3001 HOST_GRAFANA_PORT

# ── 9. Write docker-compose.override.yml ─────────────────────────────────────
OVERRIDE_FILE="${SCRIPT_DIR}/docker-compose.override.yml"
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

# ── 10. Docker Compose bring-up ───────────────────────────────────────────────
echo
box "━━━ Bringing up the stack ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$SCRIPT_DIR"

log "Starting infrastructure services (postgres, redis, botapi)..."
docker compose up -d postgres redis botapi

log "Waiting for infrastructure to be healthy (up to 90 s)..."
wait_healthy() {
    local svc timeout=90 elapsed=0
    for svc in "$@"; do
        while true; do
            status=$(docker compose ps --format json "$svc" 2>/dev/null \
                | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('Health',''))" \
                2>/dev/null || echo "")
            # Also accept "running" for services without health checks
            running=$(docker compose ps "$svc" 2>/dev/null | grep -c "Up" || true)
            if [[ "$status" == "healthy" || ( -z "$status" && "$running" -gt 0 ) ]]; then
                log "${svc} is healthy."
                break
            fi
            [[ "$elapsed" -ge "$timeout" ]] && die "Timed out waiting for ${svc} to become healthy."
            sleep 3; elapsed=$((elapsed + 3))
        done
    done
}
wait_healthy postgres redis botapi

log "Running database migrations..."
docker compose run --rm api python -m api.cli migrate

log "Seeding super-admin account..."
docker compose run --rm api python -m api.cli seed-admin || \
    warn "seed-admin returned non-zero (admin may already exist — continuing)."

log "Starting all services..."
docker compose up -d

# ── 11. Systemd service ───────────────────────────────────────────────────────
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
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
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

# ── 12. Post-install summary ──────────────────────────────────────────────────
echo
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
box "  tg-cms installed successfully"
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo -e "  Web back-office : ${CYAN}https://${APP_DOMAIN}${RESET}"
echo -e "  API docs        : ${CYAN}https://${APP_DOMAIN}/api/docs${RESET}"
echo -e "  Grafana         : ${CYAN}http://$(hostname -I | awk '{print $1}'):${HOST_GRAFANA_PORT}${RESET}"
echo -e "  Admin login     : ${BOLD}admin${RESET} / ${BOLD}${SEED_ADMIN_PASSWORD}${RESET}"
echo
echo -e "${YELLOW}${BOLD}  ⚠  REQUIRED NEXT STEP — Userbot first-run login (interactive):${RESET}"
echo
echo -e "     ${BOLD}docker compose run --rm -it userbot python -m userbot.login${RESET}"
echo -e "     (Enter phone number → verification code → 2FA password if set)"
echo -e "     Then: ${BOLD}docker compose restart userbot${RESET}"
echo
echo -e "  Manage the stack:"
echo -e "     ${BOLD}sudo systemctl {start|stop|restart|status} tg-cms${RESET}"
echo -e "     ${BOLD}docker compose logs -f${RESET}"
echo
box "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
