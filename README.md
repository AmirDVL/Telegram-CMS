# Telegram CMS Bot

A **single-tenant** system that unifies content from third-party Telegram
channels into one destination channel, with a CMS as the central store and
editorial layer.

- A **Telethon userbot** (MTProto, logged in as a real Telegram account) reads
  posts from third-party source channels it has joined. (A standard Bot API bot
  **cannot** read posts from channels it is not admin of — this is why the
  userbot exists; it is not optional.)
- Each post is **normalized independently** (no merging): source formatting is
  stripped → a consistent template is applied → source-channel label + tags are
  stamped. Exact duplicates are deduped.
- An **aiogram 3 Bot API bot** publishes normalized posts to a single flat
  destination channel.
- A **React/Next.js back-office** mirrors the editorial queue and manages source
  channels, templates, policies, tag vocabulary, and audit history.

## Architecture

```
source channels ──► userbot (Telethon) ──► Postgres ◄──► api (FastAPI) ◄──► web (Next.js)
                          │  media dl        ▲   ▲                            │
                          ▼                   │   │  read/write draft        │
                       ARQ normalize ─► worker ┤   │                          │
                                              │   │                            ▼
                                              ▼   │                        browser
                                 editor supergroup ◄── bot (aiogram 3) ── publish ──► dest channel
                                     (draft cards)    ▲                         (via local Bot API server)
                                                      │ ARQ publish / scheduled
                                                      └─ reconcile on boot
```

Cross-process coordination is **Postgres + ARQ jobs only** — the `api` and
`bot` never call each other directly. This keeps the bot the sole owner of
Telegram publishing.

## Services (`docker-compose.yml`)

| Service  | Role |
|----------|------|
| `userbot` | Telethon long-running process: subscribes to source channels, downloads media, inserts `posts`, enqueues `normalize`. |
| `worker`  | ARQ worker: `normalize` + `prune_dedupe` jobs + scheduled-publish reconcile. |
| `bot`     | aiogram 3: admin commands, draft cards with inline keyboards, `publish` worker (idempotent, spaced), delayed scheduled jobs. |
| `api`     | FastAPI back-office: CRUD + draft-queue + audit + JWT auth. |
| `web`     | Next.js back-office UI. |
| `postgres` | Primary store. |
| `redis`   | ARQ queue + delayed jobs + short-lived caches. |
| `botapi`  | Official `telegram-bot-api` local server (≤2 GB uploads). |
| `caddy`   | Reverse proxy + automatic TLS. |

## Quick start

Run the installer as root. It detects your package manager, installs Docker if
needed, generates all secrets, prompts for Telegram credentials, checks for port
conflicts, writes `.env` and `docker-compose.override.yml`, brings up the stack,
and registers a systemd service for automatic boot startup.

```bash
sudo bash install.sh
```

After the installer finishes, complete the one step that requires an interactive
TTY — the first-run userbot login:

```bash
docker compose run --rm -it userbot python -m userbot.login
# Enter: phone number → verification code → 2FA password (if set)
docker compose restart userbot
```

Re-running `install.sh` at any time is safe — it is fully idempotent and will
prompt before touching existing secrets.

**Zero-touch updates:** `install.sh` can optionally install a systemd timer
that polls the tracked git ref every ~5 minutes, rebuilds, health-gates, and
auto-rolls back on failure. A canary host tracks `main` and promotes `stable`
after a healthy rebuild; production hosts track `stable` (canary-verified
commits only). See [`docs/FLEET_UPDATES.md`](docs/FLEET_UPDATES.md).

See [`docs/RUNBOOK.md`](docs/RUNBOOK.md) for manual first-run steps, adding a
source channel, rotating the userbot session, rotating secrets, and
backup/restore.

## Documentation

| Document | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Data flow, state machine, dedupe, security |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | All environment variables, defaults, required flags |
| [`docs/BOT_GUIDE.md`](docs/BOT_GUIDE.md) | Editor workflow, inline buttons, tags, templates, scheduling |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Operational procedures, backup/restore, failure handling |
| [`docs/FLEET_UPDATES.md`](docs/FLEET_UPDATES.md) | Zero-touch fleet updates: topology, canary/production setup, rollback, caveats |
| [`docs/api/`](docs/api/) | Full REST API reference (auth, queue, tags, templates, channels, admins, audit) |

## Observability

The API exposes a **Prometheus `/metrics`** endpoint (scraped at `api:8000/metrics`)
covering HTTP request latency/count and **ARQ queue depth** for both the `worker`
and `bot` queues. A ready-to-run stack ships in `docker-compose.yml`:

- **prometheus** — scrapes the API every 15s (config in `observability/prometheus.yml`).
- **grafana** — exposed on host port `3001` with a provisioned Prometheus
  datasource and an overview dashboard (`observability/grafana/dashboards/`).
  Log in with `admin` / `GRAFANA_ADMIN_PASSWORD` (default `admin`).

> Cross-process coordination is already **Postgres + ARQ-on-Redis** (a dedicated
> broker + task-queue framework); the queue-depth metric makes that brokering
> observable rather than adding a second, competing queue system.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs `ruff` (lint) and `pytest` on
every push and pull request. Tests mock the Telegram-publishing boundary (ARQ
enqueue) and cover the deduplication logic (`shared/dedupe.py`), normalize
routing (`worker/normalize.py`), and a `/metrics` endpoint smoke test — no
Postgres/Redis required.

## Linking Telegram accounts for bot inline buttons

After first login, editors who need to approve/reject posts via the Telegram
inline buttons must have their Telegram user id linked to their web account.
A **super_admin** does this via the web back-office → **Admins** → edit the
user → set **Telegram User ID** (obtainable via [@userinfobot](https://t.me/userinfobot)).
Without this, button presses are rejected and logged as `callback-unlinked-user`.

## Operational note (userbot)

A **real Telegram user account** with 2FA is required for the userbot. Use a
dedicated account — not a personal one. The operator is responsible for account
acquisition, 2FA, and accepting Telegram ToS/flood-risk. The `.session` file is
kept in a persistent volume (never baked into the image); the 2FA password is
supplied via env secret.

## Configuration defaults (plan §9)

`install.sh` generates the secrets below automatically. All other settings use
the defaults shown here; edit `.env` afterwards to override any of them.

| Setting | Default | Env var |
|---|---|---|
| Postgres password | auto-generated | `POSTGRES_PASSWORD` |
| Redis password | auto-generated | `REDIS_PASSWORD` |
| JWT secret | auto-generated | `JWT_SECRET` |
| Seed admin password | auto-generated | `SEED_ADMIN_PASSWORD` |
| Grafana admin password | auto-generated | `GRAFANA_ADMIN_PASSWORD` |
| Dedupe lookback window | 7 days | `DEDUPE_LOOKBACK_DAYS` |
| Audit-log retention | 90 days | `AUDIT_RETENTION_DAYS` |
| Media retention on volume | 30 days post-publish | `MEDIA_RETENTION_DAYS` |
| Max concurrent publishes | 1 (spaced) | `MAX_CONCURRENT_PUBLISHES` |
| Publish spacing | 2.0 s | `PUBLISH_SPACING_SECONDS` |
| Max media size | 2 GiB | `MEDIA_MAX_SIZE_DEFAULT` |
