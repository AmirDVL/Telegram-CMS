# Fleet Updates — Zero-Touch Automatic Updates

tg-cms ships a **zero-touch update** system that lets every deployed host detect
a new release, rebuild its local images, health-gate the result, and auto-roll
back the code if the new build is broken — all without operator action.

## Topology

```
        github.com/AmirDVL/glm-testing
        main ───(canary verified healthy)──► stable
          │                                    │
   ┌──────┴──────┐                    ┌────────┴─────────┐
   │ CANARY host │                    │ 19 PRODUCTION    │
   │ tracks main │                    │ hosts track      │
   │ promotes    │                    │ stable           │
   │ stable on   │                    │ (canary-verified)│
   │ health-pass │                    └──────────────────┘
   └─────────────┘
```

Two fleet roles:

| Role | Tracks | Promotes |
|------|--------|----------|
| `canary` | `origin/main` | advances `stable` on health-pass |
| `production` | `origin/stable` | never promotes; always gets canary-verified commits |

Because production hosts only ever update to a ref that the canary already
verified healthy, a broken build is caught on one host before it reaches the
fleet.

## How promotion works

When the canary host successfully rebuilds and all services pass the health gate:

1. If a push token is configured (`FLEET_PROMOTE_TOKEN` in `/etc/tg-cms/fleet.conf`),
   the canary pushes `HEAD` to `refs/heads/stable` on the remote automatically.
2. If no push token is configured, the `auto-update.sh` script logs
   `healthy — stable advanced by CI/operator` and exits 0. A CI job or an
   operator runs `git push origin main:stable` to advance the production tier.

Production hosts poll `origin/stable` every ~5 minutes and rebuild only when
that ref advances — so they inherit only canary-verified commits.

## One-time remote setup

Before any host can track `origin/stable`, the branch must exist:

```bash
# Run once from any machine with push access:
git push origin main:stable
```

## Setting up a canary host

During `install.sh`, answer:

```
Enable automatic zero-touch updates? [Y/n]  Y
Role [production]:  canary
GitHub push token for stable promotion (blank = use CI/operator):  <token or blank>
Alert chat ID for update/rollback notifications (blank = none):  <chat id>
```

Or configure `/etc/tg-cms/fleet.conf` manually (see `fleet/fleet.conf.example`):

```
FLEET_ROLE=canary
FLEET_TRACK_REF=origin/main
FLEET_PROMOTE_REMOTE=origin
FLEET_PROMOTE_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxx
```

## Setting up a production host

During `install.sh`, accept the defaults:

```
Enable automatic zero-touch updates? [Y/n]  Y
Role [production]:  <enter>
```

Or set in `/etc/tg-cms/fleet.conf`:

```
FLEET_ROLE=production
FLEET_TRACK_REF=origin/stable
```

## Operational commands

### Pause updates

```bash
sudo systemctl disable --now tg-cms-update.timer
```

Re-enable with:

```bash
sudo systemctl enable --now tg-cms-update.timer
```

### Force an immediate update check

```bash
sudo systemctl start tg-cms-update.service
```

### Read update status and logs

```bash
# Last run result (healthy / failed):
systemctl status tg-cms-update

# Full live log of the updater:
journalctl -u tg-cms-update -f

# Last N lines:
journalctl -u tg-cms-update -n 100 --no-pager
```

### Check timer schedule

```bash
systemctl list-timers tg-cms-update.timer
```

### Verify fleet config

```bash
sudo cat /etc/tg-cms/fleet.conf
```

## Auto-rollback

If the health gate does not pass within `HEALTH_TIMEOUT` seconds (default 180):

1. `git reset --hard $PREV` (reverts to the last known-good git ref).
2. `docker compose build && docker compose up -d --remove-orphans` (rebuilds the
   old code).
3. Health gate is re-run on the rolled-back stack.
4. A Telegram alert is sent (if `FLEET_ALERT_CHAT_ID` and `BOT_TOKEN` are set).
5. The updater exits non-zero — visible in `systemctl status tg-cms-update` and
   `journalctl -u tg-cms-update`.

The rollback is **code-only**: git ref + container images are reverted. The
Postgres data volume and `.env`/`docker-compose.override.yml` (both gitignored)
are never touched.

## Caveats

### 1. DB migrations are not auto-downgraded

`auto-update.sh` runs `docker compose run --rm migrate` (Alembic upgrade to head
via the Python `migrate` service — the `api` service is Go) after
`git reset --hard $TARGET`. If the new migration
schema causes a health-gate failure and the updater rolls back the code to `$PREV`,
**the migration that ran is not reversed** — Alembic downgrades are risky to
automate and are omitted by design.

**Mitigation:** the canary gate is the primary defence. A schema change that
breaks health is caught on the canary host before `stable` advances, so the
fleet's production hosts never apply an incompatible migration. In the rare case
that the canary itself rolls back with a migration partially applied, a manual
Alembic downgrade may be needed:

```bash
docker compose run --rm migrate alembic downgrade -1
```

### 2. In-flight ARQ work survives container recreate

ARQ jobs live in Redis/Postgres, not in container memory. `docker compose up -d`
recreates only changed containers and the ARQ workers reconnect automatically.
Jobs that were executing at the moment of recreate are re-enqueued on the next
worker startup (`restart: unless-stopped` + healthchecks already cover this).
No in-flight work is lost.

### 3. Fetch auth must be non-interactive

The updater sets `GIT_TERMINAL_PROMPT=0` before every `git fetch`. If the repo
is private, the host's git credential must allow unattended fetches — embed the
token in the remote URL or configure a credential helper:

```bash
# Embed token in remote URL (survives `git reset --hard`):
git remote set-url origin https://<token>@github.com/AmirDVL/glm-testing.git
```

If authentication fails, `auto-update.sh` logs a clear warning and exits 0 (so
the timer keeps firing and retrying on the next tick), rather than hanging and
blocking the lock.

### 4. Stable promotion requires write access on the canary only

`FLEET_PROMOTE_TOKEN` is stored in `/etc/tg-cms/fleet.conf` (mode 600) on the
canary host only. Production hosts never hold write credentials. The alternative
is a CI job (e.g. GitHub Actions) that watches for a healthy canary signal and
fast-forwards `stable` without any host holding a token.
