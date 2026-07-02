# apigo — back-office API (Go)

A footprint-optimised reimplementation of the Python FastAPI back-office (`api/`)
as a single static Go binary. It serves the **same `/api` surface** the Next.js
`web` consumes, reads the **same Postgres schema** (owned by Alembic — this
service runs no migrations), and enqueues the **same ARQ `publish` jobs** the
Python services consume.

Userbot (Telethon) and bot (aiogram) stay in Python — only the API moved.

## Why it exists

The Python API stack (uvicorn + FastAPI + SQLAlchemy + asyncpg + pydantic on
`python:3.12-slim`) idles around ~80–150 MB RSS. This binary idles around
~10–20 MB in a ~15–30 MB distroless image — meaningful on the small-VPS tiers.

## Layout (flat `package main`)

| File | Responsibility |
|------|----------------|
| `main.go`, `server.go` | wiring, router, graceful shutdown, container healthcheck |
| `config.go` | env config (mirrors `shared/config.py`) |
| `models.go` | DB row structs + response DTOs (mirror `api/schemas.py`) + enums |
| `auth_jwt.go`, `auth_argon2.go`, `auth_mw.go` | HS256 JWT, argon2id verify/hash, role middleware |
| `cors.go`, `metrics.go`, `ratelimit.go` | middleware (CORS, Prometheus, Redis rate limit) |
| `enqueue.go` | produce-only ARQ `publish` jobs (JSON serializer) |
| `aiclient.go` | OpenAI-compatible call for `/source-channels/{id}/ai/test` |
| `handlers_*.go` | endpoint handlers |
| `store.go`, `patch.go`, `dberr.go` | DB helpers, presence-aware PATCH, error mapping |

## Compatibility contracts (must stay in lockstep with the Python services)

- **JWT** — HS256 with `JWT_SECRET`; claims `{sub, admin_id, role, token_type, iat,
  exp}` identical to `shared/security.py`.
- **Passwords** — argon2id PHC strings compatible with argon2-cffi (verify existing
  hashes; new hashes verify under Python too).
- **ARQ** — `enqueue.go` writes `SET arq:job:<uuid> = json({t,f,a,k,et})` + `ZADD
  arq:queue:bot <score> <uuid>`. Requires the Python side to use the **JSON** job
  serializer (`shared/tasks.py`). Covered by `tests/test_arq_json_serializer.py`.
- **Routing** — routes are served at the root (`/auth/login`, …); Caddy's
  `handle_path /api/*` strips `/api` before proxying.
- **Refresh cookie** — name `refresh_token`, `HttpOnly`, `SameSite=Lax`, `Secure` in
  prod, `Path=/api/auth`.

## Build & test

```bash
cd apigo
go mod tidy        # generates go.sum (no network-free lockfile is committed)
go vet ./...
go test ./...      # pure unit tests (JWT, argon2, ARQ job body, slugify)
go build -o /tmp/api .
```

Run locally (needs Postgres + Redis reachable via env):

```bash
JWT_SECRET=dev-secret POSTGRES_DSN=postgres://cms:cms@localhost:5432/cms \
  REDIS_URL=redis://localhost:6379/0 API_PORT=8000 go run .
```

## Container

`Dockerfile` builds a static binary onto `distroless/static`. The compose `api`
service points at it; the healthcheck is the binary itself (`/api healthcheck`),
since distroless has no shell/curl. Rollback to the Python API by repointing the
`api` service build at `Dockerfile.python` with the uvicorn command.
