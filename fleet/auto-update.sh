#!/usr/bin/env bash
# fleet/auto-update.sh — zero-touch per-host updater for tg-cms
#
# Triggered by tg-cms-update.timer (every ~5 min). Fetches the tracked git ref,
# pulls the CI-built images for that commit and re-deploys if the ref advanced,
# health-gates the result, and auto-rolls-back on failure. Writes structured
# status for journald.
#
# Config sourced from /etc/tg-cms/fleet.conf (written by install.sh, mode 600).
#
# -E  : ERR trap inherits into shell functions.
# -e  : abort on any unhandled non-zero command.
# -u  : abort on use of an unset variable.
# -o pipefail : a pipeline fails if any stage fails.
set -Eeuo pipefail

# ── Colour helpers (match install.sh exactly) ─────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
die()  { echo -e "${RED}[✗]${RESET} $*" >&2; exit 1; }

trap 'rc=$?; echo -e "${RED}[✗] auto-update aborted at line ${LINENO} (exit ${rc}).${RESET}" >&2' ERR

# ── Singleton lock — prevents overlapping timer firings ───────────────────────
LOCK_FILE="/run/tg-cms-update.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    warn "Another tg-cms-update run is already in progress — skipping."
    exit 0
fi

# ── Load host configuration ───────────────────────────────────────────────────
FLEET_CONF="/etc/tg-cms/fleet.conf"
[[ -f "$FLEET_CONF" ]] || die "Fleet config not found at ${FLEET_CONF}. Run install.sh first."
# shellcheck source=/dev/null
source "$FLEET_CONF"

# Mandatory variables (install.sh always writes these)
: "${INSTALL_DIR:?INSTALL_DIR must be set in ${FLEET_CONF}}"
: "${DC_EXEC:?DC_EXEC must be set in ${FLEET_CONF}}"
: "${FLEET_ROLE:?FLEET_ROLE must be set in ${FLEET_CONF}}"
: "${FLEET_TRACK_REF:?FLEET_TRACK_REF must be set in ${FLEET_CONF}}"

# health-gate.sh runs as a child process, so DC_EXEC must be exported to reach it
# (it may legitimately contain a space, e.g. "docker compose" — the v2 plugin).
export DC_EXEC

# Optional variables (default to empty/safe values)
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-180}"
FLEET_PROMOTE_REMOTE="${FLEET_PROMOTE_REMOTE:-}"
FLEET_PROMOTE_TOKEN="${FLEET_PROMOTE_TOKEN:-}"
FLEET_ALERT_CHAT_ID="${FLEET_ALERT_CHAT_ID:-}"
BOT_TOKEN="${BOT_TOKEN:-}"
GHCR_USER="${GHCR_USER:-}"
GHCR_PULL_TOKEN="${GHCR_PULL_TOKEN:-}"

# Path to this fleet directory (sibling scripts live here)
FLEET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Verify we are in a git work tree ─────────────────────────────────────────
cd "$INSTALL_DIR"
if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    die "INSTALL_DIR '${INSTALL_DIR}' is not inside a git work tree."
fi

# ── Registry auth (private GHCR pulls) ────────────────────────────────────────
# Optional: only needed when the GHCR packages are private. Token lives in
# fleet.conf (mode 600) and is piped to docker login — never written elsewhere.
if [[ -n "$GHCR_USER" && -n "$GHCR_PULL_TOKEN" ]]; then
    if echo "$GHCR_PULL_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin &>/dev/null; then
        log "Logged in to ghcr.io as ${GHCR_USER}."
    else
        warn "ghcr.io login failed — private image pulls may fail."
    fi
fi

# ── Non-interactive fetch (fail cleanly rather than hanging for a prompt) ─────
# GIT_TERMINAL_PROMPT=0 ensures git does not block waiting for credentials.
log "Fetching from origin..."
if ! GIT_TERMINAL_PROMPT=0 git fetch --quiet origin 2>&1; then
    warn "git fetch failed — cannot check for updates. Check git credentials."
    warn "Hint: embed credentials in the remote URL or configure a credential helper."
    exit 0   # non-fatal; try again next timer tick
fi

# ── Ref comparison (the common, cheap path) ───────────────────────────────────
TARGET="$(git rev-parse "${FLEET_TRACK_REF}" 2>/dev/null)" \
    || die "Tracked ref '${FLEET_TRACK_REF}' does not exist. Has the remote been set up?"
CURRENT="$(git rev-parse HEAD)"

if [[ "$TARGET" == "$CURRENT" ]]; then
    log "Already at ${TARGET:0:12} — nothing to do."
    exit 0
fi

log "Update detected: ${CURRENT:0:12} → ${TARGET:0:12}"
PREV="$CURRENT"

# ── Helper: persist the image tag for this commit ─────────────────────────────
# Persist IMAGE_TAG into .env so compose pulls/runs the image built for this exact
# commit — and so the boot-time tg-cms.service `up -d` uses the same tag. The git
# SHA is the fleet's version; CI publishes ghcr.io/amirdvl/telegram-cms-*:<sha>.
write_image_tag() {
    local sha="$1"
    IMAGE_TAG="$sha"
    export IMAGE_TAG
    local env_file="${INSTALL_DIR}/.env"
    if grep -q '^IMAGE_TAG=' "$env_file" 2>/dev/null; then
        sed -i "s|^IMAGE_TAG=.*|IMAGE_TAG=${sha}|" "$env_file"
    else
        printf '\nIMAGE_TAG=%s\n' "$sha" >> "$env_file"
    fi
}

# Pull the CI-built images for the current IMAGE_TAG. Returns non-zero if the
# registry doesn't have them yet (CI still building) or is unreachable — callers
# decide whether to retry (forward) or fall back to cached images (rollback).
pull_images() {
    local label="$1"
    log "[${label}] Pulling images (IMAGE_TAG=${IMAGE_TAG:0:12})..."
    $DC_EXEC pull
}

# Run migrations (idempotent) + (re)start services from whatever images are local.
deploy() {
    local label="$1"
    log "[${label}] Running migrations (idempotent)..."
    # Migrations run via the Python `migrate` service (api is Go, no Alembic).
    $DC_EXEC run --rm migrate || \
        warn "[${label}] Migration step exited non-zero (this may be expected on rollback)."

    log "[${label}] Restarting services..."
    $DC_EXEC up -d --remove-orphans
}

# ── Helper: send a Telegram alert (best-effort; errors are non-fatal) ─────────
tg_alert() {
    local text="$1"
    [[ -z "$FLEET_ALERT_CHAT_ID" || -z "$BOT_TOKEN" ]] && return 0
    curl -fsS --max-time 10 \
        "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${FLEET_ALERT_CHAT_ID}" \
        -d "text=${text}" \
        -d "parse_mode=HTML" &>/dev/null || true
}

# ── Helper: promote stable ref (canary only, best-effort) ────────────────────
promote_stable() {
    local sha="$1"
    if [[ -z "$FLEET_PROMOTE_REMOTE" || -z "$FLEET_PROMOTE_TOKEN" ]]; then
        log "Canary healthy — stable is advanced by CI/operator (no push token configured)."
        return 0
    fi
    log "Promoting stable to ${sha:0:12}..."
    # Inject the token into the remote URL for this push only.
    local remote_url
    remote_url="$(git remote get-url "$FLEET_PROMOTE_REMOTE" 2>/dev/null)" \
        || { warn "Remote '${FLEET_PROMOTE_REMOTE}' not found — skipping promotion."; return 0; }
    # Replace https:// with https://<token>@ so no credentials are needed on disk.
    local auth_url="${remote_url/https:\/\//https:\/\/${FLEET_PROMOTE_TOKEN}@}"
    if GIT_TERMINAL_PROMPT=0 git push "$auth_url" "${sha}:refs/heads/stable" --quiet 2>&1; then
        log "Stable promoted to ${sha:0:12}."
    else
        warn "Stable promotion failed — promote manually or let CI handle it."
    fi
}

# ── Forward update ────────────────────────────────────────────────────────────
log "Applying update: resetting to ${TARGET:0:12}..."
git reset --hard "$TARGET"
write_image_tag "$TARGET"

# Pull the images CI built for this SHA. If they aren't published yet (CI still
# running) or the registry is unreachable, leave the running stack untouched and
# retry on the next timer tick — never rebuild on the host.
if ! pull_images "update"; then
    warn "Images for ${TARGET:0:12} not available yet (CI may still be building). Reverting tree; will retry next tick."
    git reset --hard "$PREV"
    write_image_tag "$PREV"
    exit 0
fi

if ! deploy "update"; then
    warn "Deploy step encountered errors."
fi

# ── Health gate ───────────────────────────────────────────────────────────────
log "Running health gate (timeout ${HEALTH_TIMEOUT}s)..."
if "${FLEET_DIR}/health-gate.sh" "$HEALTH_TIMEOUT"; then
    # ── Healthy path ──────────────────────────────────────────────────────────
    log "Health gate passed at ${TARGET:0:12}."

    log "Pruning old image layers..."
    docker image prune -f &>/dev/null || true

    if [[ "$FLEET_ROLE" == "canary" ]]; then
        promote_stable "$TARGET"
    fi

    tg_alert "tg-cms updated to <code>${TARGET:0:12}</code> on $(hostname) (${FLEET_ROLE})"
    log "Update complete: ${PREV:0:12} → ${TARGET:0:12}"
    exit 0
fi

# ── Unhealthy path — auto-rollback ────────────────────────────────────────────
warn "Health gate FAILED after ${HEALTH_TIMEOUT}s. Rolling back to ${PREV:0:12}..."

git reset --hard "$PREV"
write_image_tag "$PREV"
pull_images "rollback" || warn "Pull failed on rollback — using locally cached images."
deploy "rollback" || true

log "Re-running health gate on rolled-back code..."
if "${FLEET_DIR}/health-gate.sh" "$HEALTH_TIMEOUT"; then
    warn "Rollback health gate passed — stack is back on ${PREV:0:12}."
else
    warn "Rollback health gate also failed. Manual intervention required."
fi

tg_alert "$(printf '<b>tg-cms update FAILED</b> on <code>%s</code> (%s)\nRolled back from <code>%s</code> to <code>%s</code>' \
    "$(hostname)" "$FLEET_ROLE" "${TARGET:0:12}" "${PREV:0:12}")"

die "Update to ${TARGET:0:12} failed health gate; rolled back to ${PREV:0:12}. See journal for details."
