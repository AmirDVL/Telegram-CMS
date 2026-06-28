#!/usr/bin/env bash
# fleet/health-gate.sh — polls Compose health states until all services pass
#
# Usage:  health-gate.sh [TIMEOUT_SECONDS]
#   TIMEOUT_SECONDS defaults to HEALTH_TIMEOUT env var, then 180 s.
#
# Returns 0 when all services with a defined healthcheck are "healthy" and all
# services without a healthcheck are at least "running".
# Returns 1 on timeout.
#
# Reused by fleet/auto-update.sh for both the forward update and rollback verify.
set -Eeuo pipefail

# ── Colour helpers (match install.sh / auto-update.sh exactly) ───────────────
YELLOW='\033[1;33m'; GREEN='\033[0;32m'; RED='\033[0;31m'; RESET='\033[0m'

log()  { echo -e "${GREEN}[+]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }

# ── Config ────────────────────────────────────────────────────────────────────
TIMEOUT="${1:-${HEALTH_TIMEOUT:-180}}"
POLL_INTERVAL=5

# DC_EXEC is sourced from the caller's environment (set in fleet.conf and
# exported by auto-update.sh). Fall back to "docker compose" for standalone use.
DC_EXEC="${DC_EXEC:-docker compose}"

# ── Services that have a healthcheck in docker-compose.yml ───────────────────
# These must reach "healthy" status. If docker reports "none", we treat the
# service as pass-through (no healthcheck defined), checking only "running".
EXPECTED_SERVICES=(postgres redis botapi worker userbot bot api web)

log "Health gate: waiting up to ${TIMEOUT}s for all services to be healthy..."

deadline=$(( $(date +%s) + TIMEOUT ))

check_all_healthy() {
    # `docker compose ps --format json` emits one JSON object per line (jsonl).
    # We parse Name, Status, and Health fields from each line.
    local ps_output
    if ! ps_output="$($DC_EXEC ps --format json 2>/dev/null)"; then
        warn "  'docker compose ps --format json' failed — retrying..."
        return 1
    fi

    # If output is empty (no containers up yet), not healthy.
    [[ -n "$ps_output" ]] || return 1

    local all_ok=true
    local svc health state

    for svc in "${EXPECTED_SERVICES[@]}"; do
        # Match by the Service field (short name, e.g. "api").
        # docker compose ps --format json outputs per-container JSON lines.
        local line
        line="$(echo "$ps_output" | grep -i "\"Service\":\"${svc}\"" 2>/dev/null || true)"

        if [[ -z "$line" ]]; then
            # Container not present yet — not ready.
            warn "  ${svc}: not found in 'docker compose ps' output"
            all_ok=false
            continue
        fi

        # Extract Health and State fields. Use sed for portability (no jq required).
        health="$(echo "$line" | sed -n 's/.*"Health":"\([^"]*\)".*/\1/p' || true)"
        state="$(echo  "$line" | sed -n 's/.*"State":"\([^"]*\)".*/\1/p'  || true)"

        if [[ -z "$health" || "$health" == "none" ]]; then
            # No healthcheck — pass if running.
            if [[ "$state" == "running" ]]; then
                log "  ${svc}: running (no healthcheck — pass)"
            else
                warn "  ${svc}: state='${state}' (expected running)"
                all_ok=false
            fi
        elif [[ "$health" == "healthy" ]]; then
            log "  ${svc}: healthy"
        else
            warn "  ${svc}: health='${health}' state='${state}'"
            all_ok=false
        fi
    done

    $all_ok
}

# ── Fallback: curl the /healthz endpoints inside the containers ───────────────
# Used when docker compose ps --format json is unavailable (e.g. older Compose).
check_via_curl() {
    # Map of service → internal port. Services without /healthz (caddy, grafana,
    # prometheus, redis, postgres, botapi) are checked for "running" only via ps.
    declare -A SVC_PORT=(
        [api]=8000
        [bot]=8082
        [worker]=8083
        [userbot]=8084
    )
    # web uses a different path
    declare -A SVC_PATH=(
        [api]=/healthz
        [bot]=/healthz
        [worker]=/healthz
        [userbot]=/healthz
        [web]=/api/health
    )
    SVC_PORT[web]=3000

    local all_ok=true
    local svc port path

    for svc in "${!SVC_PORT[@]}"; do
        port="${SVC_PORT[$svc]}"
        path="${SVC_PATH[$svc]}"
        if $DC_EXEC exec -T "$svc" curl -fsS --max-time 5 \
                "http://localhost:${port}${path}" &>/dev/null; then
            log "  ${svc}: /healthz OK (curl fallback)"
        else
            warn "  ${svc}: /healthz FAILED (curl fallback)"
            all_ok=false
        fi
    done

    $all_ok
}

# ── Poll loop ─────────────────────────────────────────────────────────────────
while [[ $(date +%s) -lt $deadline ]]; do
    if check_all_healthy 2>/dev/null || check_via_curl 2>/dev/null; then
        log "All services healthy."
        exit 0
    fi
    remaining=$(( deadline - $(date +%s) ))
    warn "Not all healthy yet — ${remaining}s remaining. Retrying in ${POLL_INTERVAL}s..."
    sleep "$POLL_INTERVAL"
done

echo -e "${RED}[✗]${RESET} Health gate timed out after ${TIMEOUT}s." >&2
exit 1
