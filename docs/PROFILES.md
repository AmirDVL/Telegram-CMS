# Deployment Tiers & Compose Profiles

The stack ships as a single `docker-compose.yml`, but not every host needs every
service. A 1 GB VPS can run the ingest→publish pipeline fine, but the Next.js web
back-office (200–400 MB) can OOM it. To fit small hosts, services are grouped
into [Docker Compose
profiles](https://docs.docker.com/compose/profiles/) selected by the
`COMPOSE_PROFILES` line in `.env`.

`install.sh` asks which tier to run and writes the matching `COMPOSE_PROFILES`.
Because every `docker compose` command (and the fleet auto-updater) reads `.env`
automatically, the selection applies to `build`, `up`, `ps`, `config`, and the
health gate with no extra flags.

## Profiles

| Service | Profile | Purpose |
|---------|---------|---------|
| `postgres`, `redis`, `userbot`, `worker`, `bot` | _(none — core)_ | Always run. The ingest → normalize → publish pipeline + bot admin commands. |
| `api`, `web`, `caddy` | `backoffice` | REST API, Next.js back-office UI, and the TLS reverse proxy in front of them. |
| `botapi` | `largemedia` | Local telegram-bot-api server for uploads up to 2 GB. |

Core services have no `profiles:` key, so they always start. The web/api/caddy
trio is coupled into one `backoffice` profile because the REST API's only in-stack
consumer is the web UI, and Caddy needs both upstreams present.

## Tiers

| Tier | `COMPOSE_PROFILES` | Rough RAM | What you get |
|------|--------------------|-----------|--------------|
| **minimal** | _(empty)_ | ~1 GB | Core only. Management is **bot commands only**. Uses the **cloud** Telegram API with a **50 MB** media cap. No web UI, no TLS, no domain needed. |
| **standard** | `largemedia` | ~2 GB | Core + local Bot API server (media up to 2 GB). Still bot-commands-only management. |
| **full** | `backoffice,largemedia` | ~3 GB | Core + web back-office, REST API, TLS. **Default.** |

## Cloud vs local Bot API

When the `largemedia` profile is **off**, the `botapi` container is not started and
`install.sh` writes an **empty** `BOT_API_SERVER_URL`. `bot/client.py` then builds
the bot against Telegram's hosted API (`api.telegram.org`), which caps uploads at
50 MB. To match, `MEDIA_MAX_SIZE_DEFAULT` is set to `52428800` (50 MB) so the
userbot omits oversized media at ingest (`userbot/ingest.py`) instead of failing
the upload later. The bot also drops any over-cap file defensively at send time.

`Settings.use_local_bot_api` (in `shared/config.py`) reflects the mode:
`True` when a server URL is set, `False` in cloud mode.

## Changing tier on a running host

Edit `COMPOSE_PROFILES` in `.env` and recreate the stack; `--remove-orphans`
stops services that are no longer in an active profile:

```bash
# full → standard (drop web UI)
sed -i 's/^COMPOSE_PROFILES=.*/COMPOSE_PROFILES=largemedia/' .env
docker compose up -d --remove-orphans
```

When moving **off** `largemedia`, also set `BOT_API_SERVER_URL=` (empty) and
`MEDIA_MAX_SIZE_DEFAULT=52428800`. The simplest path is to **re-run `install.sh`**
and pick the tier — it rewrites all of these consistently.

Inspect what a given selection resolves to without starting anything:

```bash
COMPOSE_PROFILES=largemedia docker compose config --services
```

## Notes

- **Migrations** run in every tier: `install.sh` uses `docker compose run --rm
  migrate` (a one-shot Python service on the `migrate` profile), and naming a service
  on the command line activates it regardless of profile. Its image is the same
  `Dockerfile.python` the core `worker` already builds. (The `api` service itself is
  now a Go binary with no Alembic.)
- **The fleet health gate** (`fleet/health-gate.sh`) derives its expected-service
  list from `docker compose config --services`, so it only waits on the services
  your active tier actually runs.
- **Metrics** — the Go `api` still exposes a Prometheus-format `/metrics` endpoint
  for optional external scraping; no in-stack Prometheus/Grafana is bundled.
