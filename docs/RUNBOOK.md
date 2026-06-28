# Runbook — Telegram CMS Bot

Operational procedures for the single-tenant Telegram CMS deployment.

## 0. Prerequisites

- A Linux VPS with Docker + Docker Compose.
- A **dedicated** Telegram user account for the userbot (with 2FA enabled). Do
  **not** use a personal account.
- A **Bot API bot** token from [@BotFather](https://t.me/BotFather).
- API ID / API Hash from <https://my.telegram.org> (for the userbot + local Bot
  API server).
- A **destination channel** the bot is admin of (with permission to post).
- A private **editor supergroup** the bot is admin of (for draft cards).
- A domain pointed at the VPS for Caddy automatic TLS.

## 1. First run

```bash
cp .env.example .env
# Edit .env: TELEGRAM_API_ID/HASH, BOT_TOKEN, DESTINATION_CHANNEL_ID,
# EDITOR_GROUP_ID, JWT_SECRET, SEED_ADMIN_PASSWORD, APP_DOMAIN

# 1. Start infrastructure
docker compose up -d postgres redis botapi

# 2. Apply migrations + seed the super-admin + default tags/template
docker compose run --rm api python -m api.cli migrate

# 3. First-run userbot login (interactive TTY — Telethon asks for phone/code/2FA)
docker compose run --rm -it userbot python -m userbot.login
#   -> "Session saved."  The .session file now lives in the sessiondata volume.

# 4. Start everything
docker compose up -d
```

Verify:

```bash
docker compose ps                       # all healthy
curl http://localhost/healthz 2>/dev/null || true   # via Caddy once TLS is up
# Web back-office: https://<APP_DOMAIN>  (login with SEED_ADMIN_*)
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

- **JWT_SECRET** (web auth): changing it invalidates all sessions. Update
  `.env`, then `docker compose up -d api`.
- **BOT_TOKEN**: get a new token from BotFather, update `.env`, then
  `docker compose up -d bot`.
- **TELEGRAM_2FA_PASSWORD**: update the account's 2FA in a Telegram client, set
  the new value in `.env`, then `docker compose up -d userbot`.
- **Postgres password**: change in Postgres, update `POSTGRES_DSN` in `.env`
  (the password is embedded in the DSN), update `POSTGRES_PASSWORD` for the
  Docker container itself, then restart dependent services.

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
| Draft cards missing | `bot` logs + editor group id | `EDITOR_GROUP_ID` set + bot admin of group |
| Inline Approve/Reject buttons silently rejected | `bot` logs for `callback-unlinked-user` | admin's `tg_user_id` not set — link via web back-office → Admins |
| Publish stuck / failed | `post_events` `publish_failed` + `botapi` health | local Bot API server up? `docker compose restart botapi bot` |
| Scheduled posts not firing | `worker` reconcile logs | `worker` running? overdue posts re-enqueued on boot |
| Pending posts never normalize | `userbot` logs for `requeued-orphan` | userbot reconciler re-enqueues on boot; check `worker` is healthy |
| Duplicate publishes | `published_dedupe` lookback | `DEDUPE_LOOKBACK_DAYS` config; publish job is idempotent |

## 8. Monitoring (Prometheus + Grafana)

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

## 9. Open configuration (plan §9 defaults)

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
