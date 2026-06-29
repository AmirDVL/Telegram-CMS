# Runbook — Telegram CMS Bot

Operational procedures for the single-tenant Telegram CMS deployment.

## 0. Prerequisites

- A Linux VPS (Ubuntu 22.04/24.04, Debian 12, RHEL/Rocky/Alma 8–9, or similar).
  Docker + Docker Compose are installed automatically by `install.sh` if missing.
- Root / sudo access (`install.sh` must run as root).
- A **dedicated** Telegram user account for the userbot (with 2FA enabled). Do
  **not** use a personal account.
- A **Bot API bot** token from [@BotFather](https://t.me/BotFather).
- API ID / API Hash from <https://my.telegram.org> (for the userbot + local Bot
  API server).
- A **destination channel** the bot is admin of (with permission to post).
- A private **editor supergroup** the bot is admin of (for draft cards).
- A domain pointed at the VPS for Caddy automatic TLS.

## 1. First run

### Automated (recommended)

```bash
sudo bash install.sh
```

The installer will:

1. Detect the host package manager (`apt` / `dnf` / `yum`) and install Docker if
   missing.
2. Optionally configure an HTTP proxy or registry mirrors for the Docker daemon
   (prompted interactively — useful in restricted network environments).
3. Generate secure random values for `POSTGRES_PASSWORD`, `REDIS_PASSWORD`,
   `JWT_SECRET`, `SEED_ADMIN_PASSWORD`, and `GRAFANA_ADMIN_PASSWORD`.
4. Prompt for all required Telegram credentials and the public domain.
5. Check for host port conflicts on 80, 443, and 3001; offer to remap any that
   are already in use.
6. Write `.env` (mode 600) and `docker-compose.override.yml` (Redis auth +
   any remapped ports).
7. Bring up the full stack, run migrations, and seed the super-admin.
8. Install and enable `/etc/systemd/system/tg-cms.service` for automatic
   startup on boot.

The installer auto-detects the Compose CLI and supports both the modern
`docker compose` (v2 plugin) and the legacy standalone `docker-compose` (v1)
binary. It also pins `COMPOSE_PROJECT_NAME=tg-cms` in `.env`, so the project's
volumes are deterministically named `tg-cms_*` (e.g. `tg-cms_pgdata`,
`tg-cms_media`) — the names used by the backup/restore commands in §6.

Re-running `install.sh` is safe — it is fully idempotent. It preserves existing
secrets by default, **never** regenerates the Postgres password against an
already-initialized data volume (which would lock the stack out of its own
database), and reuses any existing port remaps without re-prompting.

After the installer finishes, complete the **one step that requires an interactive
TTY** — the first-run userbot login:

```bash
docker compose run --rm -it userbot python -m userbot.login
#   -> Enter phone → verification code → 2FA password (if set)
#   -> "Session saved."  The .session file now lives in the sessiondata volume.
docker compose restart userbot
```

Verify:

```bash
docker compose ps                              # all containers healthy
curl -s http://localhost:8000/healthz          # API responds
# Web back-office: https://<APP_DOMAIN>  (login with admin / <SEED_ADMIN_PASSWORD>)
```

### Manual alternative

If you need to set up without the installer:

```bash
cp .env.example .env
# Edit .env: set TELEGRAM_API_ID/HASH, BOT_TOKEN, DESTINATION_CHANNEL_ID,
# EDITOR_GROUP_ID, JWT_SECRET, SEED_ADMIN_PASSWORD, APP_DOMAIN,
# POSTGRES_PASSWORD, REDIS_PASSWORD, GRAFANA_ADMIN_PASSWORD

# 1. Start infrastructure
docker compose up -d postgres redis botapi

# 2. Apply migrations + seed the super-admin
docker compose run --rm api python -m api.cli migrate
docker compose run --rm api python -m api.cli seed-admin

# 3. First-run userbot login (interactive TTY)
docker compose run --rm -it userbot python -m userbot.login

# 4. Start everything
docker compose up -d
```

## 2. Adding a source channel

1. Join the userbot account to the target third-party channel (do this from a
   Telegram client logged into that account).
2. Find the channel's numeric id (e.g. `-1001234567890`). Channels the userbot
   is a member of are resolvable by that id.
3. In the web back-office → **Sources** → add: telegram channel id, title,
   `@username` (if public), policy (`auto` publish / `queue` approve), an
   optional source label and normalization template.
4. Restart the userbot so it subscribes to the new channel (it backfills up to
   200 recent posts, idempotently):

   ```bash
   docker compose restart userbot
   ```

For `queue` channels, posts land as draft cards in the editor supergroup and in
the web **Queue**. For `auto` channels, posts publish immediately.

## 3. Editing a post's tags / scheduling

- **Inline** (editor supergroup): tap **✅ Approve** or **🗑 Reject**.
- **Full editing** (web Queue): pick tags with the tag chips, optionally set a
  schedule time, then Approve / Schedule / Reject. The web and Telegram surfaces
  write to the same queue and append the same audit events.

## 4. Rotating the userbot session

If the account is compromised or you migrate hosts:

```bash
docker compose stop userbot
# Remove the persisted session so the next start triggers a fresh login:
docker compose run --rm --entrypoint sh userbot -c "rm -f /data/sessions/*.session*"
docker compose run --rm -it userbot python -m userbot.login
docker compose start userbot
```

> The `.session` file in `sessiondata` is the credential. Treat it as a secret.

## 5. Rotating secrets

The easiest way to rotate all auto-generated secrets at once is to re-run the
installer and answer **Y** when it asks whether to regenerate secrets:

```bash
sudo bash install.sh
```

To rotate individual secrets manually:

- **JWT_SECRET** (web auth): changing it invalidates all active sessions. Update
  `.env`, then `docker compose up -d api`.
- **BOT_TOKEN**: get a new token from BotFather, update `.env`, then
  `docker compose up -d bot`.
- **TELEGRAM_2FA_PASSWORD**: update the account's 2FA in a Telegram client, set
  the new value in `.env`, then `docker compose up -d userbot`.
- **POSTGRES_PASSWORD**: change the password in Postgres, update both
  `POSTGRES_PASSWORD` and `POSTGRES_DSN` in `.env` (the password is embedded in
  the DSN), then `docker compose up -d`.
- **REDIS_PASSWORD**: update `REDIS_PASSWORD` in `.env` and the matching literal
  in `docker-compose.override.yml` (the `redis` service `--requirepass` flag),
  then update `REDIS_URL` so the password in the DSN matches, then
  `docker compose up -d redis && docker compose restart worker bot api userbot`.

## 6. Backup / restore

```bash
# Postgres dump
docker compose exec postgres pg_dump -U cms cms > backup_$(date +%F).sql

# Media volume tarball
docker run --rm -v tg-cms_media:/media -v "$PWD":/backup alpine \
  tar czf /backup/media_$(date +%F).tar.gz -C /media .

# Restore Postgres
cat backup_YYYY-MM-DD.sql | docker compose exec -T postgres psql -U cms cms

# Restore media
docker run --rm -v tg-cms_media:/media -v "$PWD":/backup alpine \
  tar xzf /backup/media_YYYY-MM-DD.tar.gz -C /media
```

Back up the `sessiondata` volume if you do **not** want to re-login the userbot:

```bash
docker run --rm -v tg-cms_sessiondata:/data -v "$PWD":/backup alpine \
  tar czf /backup/session_$(date +%F).tar.gz -C /data .
```

## 7. Failure handling cheat-sheet

| Symptom | Check | Fix |
|---|---|---|
| Posts not arriving | `userbot` logs + `healthz` | account joined channel? session valid? `docker compose restart userbot` |
| **Userbot unhealthy / MTProto session invalid** (flood ban, 2FA/ToS change, account kicked) | `curl -s http://localhost:8084/healthz \| jq .checks.mtproto` — shows `disconnected`, `unauthorized`, `stale`, or `floodwait` | Re-run the interactive login: `docker compose stop userbot && docker compose run --rm -it userbot python -m userbot.login && docker compose start userbot` (see §4). An alert was already sent to the editor group on session loss. |
| Draft cards missing | `bot` logs + editor group id | `EDITOR_GROUP_ID` set + bot admin of group |
| Inline Approve/Reject buttons silently rejected | `bot` logs for `callback-unlinked-user` | admin's `tg_user_id` not set — link via web back-office → Admins |
| Publish stuck / failed | `post_events` `publish_failed` + `botapi` health | local Bot API server up? `docker compose restart botapi bot` |
| Scheduled posts not firing | `worker` reconcile logs | `worker` running? overdue posts re-enqueued on boot |
| Pending posts never normalize | `userbot` logs for `requeued-orphan` | userbot reconciler re-enqueues on boot; check `worker` is healthy |
| Duplicate publishes | `published_dedupe` lookback | `DEDUPE_LOOKBACK_DAYS` config; publish job is idempotent |

## 8. Managing the systemd service

`install.sh` registers `/etc/systemd/system/tg-cms.service`, which runs
`docker compose up -d --remove-orphans` on boot and `docker compose down` on
stop. Use standard `systemctl` commands to manage the stack:

```bash
sudo systemctl status  tg-cms   # show running state
sudo systemctl stop    tg-cms   # bring the whole stack down
sudo systemctl start   tg-cms   # bring the stack back up
sudo systemctl restart tg-cms   # stop then start
sudo systemctl disable tg-cms   # prevent auto-start on boot
sudo systemctl enable  tg-cms   # re-enable auto-start on boot
```

Logs are routed to the system journal:

```bash
journalctl -u tg-cms -f          # follow the service wrapper logs
docker compose logs -f            # follow individual container logs
docker compose logs -f api bot    # follow specific services
```

If you update `docker-compose.yml` or `.env`, reload the stack without touching
the systemd unit:

```bash
docker compose pull               # pull updated images (if any)
docker compose up -d              # recreate changed containers only
```

### Changing the deployment tier

The set of running services is controlled by `COMPOSE_PROFILES` in `.env`
(see [`PROFILES.md`](PROFILES.md)). To move a host between tiers, edit that line
and recreate the stack — `--remove-orphans` stops services no longer in the
active profiles:

```bash
# e.g. drop the web back-office + metrics to free RAM (full → standard)
sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=largemedia/' .env
docker compose up -d --remove-orphans
```

When moving **off** `largemedia` (no local Bot API server), also set
`BOT_API_SERVER_URL=` (empty) and `MEDIA_MAX_SIZE_DEFAULT=52428800` so the bot
uses the cloud API and omits media over 50 MB. Re-running `install.sh` and
choosing the tier does all of this for you.

## 9. Fleet updates & rollback

`install.sh` can optionally install a systemd timer that polls the tracked git
ref every ~5 minutes and zero-touch rebuilds the stack when a new commit lands.
See [`docs/FLEET_UPDATES.md`](FLEET_UPDATES.md) for the full topology and
canary/production setup guide.

### Check update status

```bash
# Last run result (healthy / failed / skipped):
systemctl status tg-cms-update

# Live log of the updater:
journalctl -u tg-cms-update -f

# When the timer next fires:
systemctl list-timers tg-cms-update.timer
```

### Pause / resume automatic updates

```bash
sudo systemctl disable --now tg-cms-update.timer   # pause
sudo systemctl enable  --now tg-cms-update.timer   # resume
```

### Force an immediate update

```bash
sudo systemctl start tg-cms-update.service
```

### After a failed update (auto-rollback)

When the health gate times out the updater automatically runs
`git reset --hard $PREV` and rebuilds the old code. Check what went wrong:

```bash
journalctl -u tg-cms-update -n 200 --no-pager   # full updater log
docker compose logs --tail=100                   # container logs
```

Once the root cause is fixed (or the bad commit is reverted on `main`/`stable`),
the next timer tick will re-attempt the update automatically.

> **Note:** DB migrations are not auto-downgraded. If a migration ran before
> rollback, you may need `docker compose run --rm api alembic downgrade -1`.
> See [`docs/FLEET_UPDATES.md`](FLEET_UPDATES.md) for details.

## 10. Monitoring (Prometheus + Grafana)

A ready-to-run observability stack ships in `docker-compose.yml`. It needs no
Python configuration — Prometheus scrapes the API's `/metrics` endpoint
internally (`api:8000/metrics`, config in `observability/prometheus.yml`).

**Grafana** is published on host port `3001`:

```
http://<host>:3001        # user: admin  /  password: GRAFANA_ADMIN_PASSWORD (default: admin)
```

On first boot it is auto-provisioned with:

- a Prometheus datasource (`observability/grafana/provisioning/datasources/`), and
- an overview dashboard (`observability/grafana/dashboards/tg-cms-overview.json`).

Change the default Grafana password before exposing port `3001` (set
`GRAFANA_ADMIN_PASSWORD` in `.env` and `docker compose up -d grafana`).

**Prometheus** has no published port; query it inside the network only:

```bash
docker compose exec prometheus wget -qO- http://localhost:9090/-/healthy
# queue depth directly from the API's /metrics:
docker compose exec api wget -qO- http://localhost:8000/metrics | grep arq_queue_depth
```

Useful signals when triaging the failure cheat-sheet below:

- `arq_queue_depth{queue="worker"}` / `{queue="bot"}` rising — jobs piling up
  (worker or bot stuck / down).
- `api_http_requests_total` / `api_http_request_duration_seconds` — API traffic
  and latency by route.

## 11. Open configuration (plan §9 defaults)

| Setting | Default | Env var |
|---|---|---|
| Dedupe lookback window | 7 days | `DEDUPE_LOOKBACK_DAYS` |
| Audit-log retention | 90 days | `AUDIT_RETENTION_DAYS` |
| Media retention on volume | 30 days post-publish | `MEDIA_RETENTION_DAYS` |
| Max concurrent publishes | 1 (spaced) | `MAX_CONCURRENT_PUBLISHES` |
| Publish spacing | 2.0 s | `PUBLISH_SPACING_SECONDS` |
| Max media size | 2 GiB | `MEDIA_MAX_SIZE_DEFAULT` |

The prune job runs daily at 04:00 (worker cron) and prunes the dedupe index +
orphaned media older than the retention windows.
