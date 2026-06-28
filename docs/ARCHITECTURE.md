# Architecture

## System Overview

This is a single-tenant Telegram content management system. A long-running Telethon MTProto userbot subscribes to one or more third-party Telegram source channels, downloads and normalises incoming content, and publishes approved posts to a single destination channel through an aiogram Bot API bot.

A FastAPI back-office API and a Next.js 14 web UI provide editorial control: reviewing drafts, managing tags and templates, scheduling posts, and administering users.

---

## Services

### userbot (Telethon MTProto)

Long-running process that maintains an authenticated MTProto user session.

**On startup:**

1. **Reconcile orphaned posts** — finds `pending` posts whose `raw_media_refs` is empty and that are older than 5 minutes. These represent rows inserted before a crash between the two ingest phases (row insert and media download). They are re-processed or marked failed as appropriate.
2. **Backfill** — fetches up to the 200 most recent messages from each enabled source channel and inserts them idempotently. A unique constraint on `(source_channel_id, source_message_id)` prevents duplicates.
3. **Live listener** — subscribes to `NewMessage` events for all enabled source channels.

**On each new message:**

1. Inserts a `Post` row with `state=pending` and `raw_media_refs=[]` to claim a primary key.
2. Downloads any attached media.
3. Updates `raw_media_refs` with the downloaded file references.
4. Enqueues a `normalize` job to `QUEUE_WORKER`.

Telegram `FloodWait` errors are handled with sleep-and-retry.

---

### worker (ARQ on `QUEUE_WORKER`)

Consumes `normalize` and `prune_dedupe` jobs from the ARQ queue.

**On startup:** runs `reconcile_scheduled` — queries for `scheduled` posts whose scheduled time has passed (up to 30 days overdue) and re-enqueues their publish jobs in batches of 100.

**`normalize` job:**

1. Loads the template assigned to the source channel (falls back to a minimal default).
2. Renders `normalized_text` via Jinja2.
3. Computes `dedupe_hash` from `raw_text` and `raw_media_refs` (see [Dedupe](#dedupe)).
4. Checks `published_dedupe` for any match within `DEDUPE_LOOKBACK_DAYS`. If a duplicate is found, sets `state=rejected` with `action=duplicate`.
5. If no duplicate: routes based on channel mode:
   - **auto** — enqueues a `publish` job to `QUEUE_BOT`.
   - **queue** — enqueues a `post_draft` job to `QUEUE_BOT`.

**Daily cron at 04:00 UTC (`prune_dedupe`):**

- Deletes `published_dedupe` rows older than `DEDUPE_LOOKBACK_DAYS`.
- Deletes `post_events` rows older than `AUDIT_RETENTION_DAYS`.
- Deletes orphaned media files on disk older than `MEDIA_RETENTION_DAYS`.

---

### bot (aiogram 3 + embedded ARQ on `QUEUE_BOT`)

Consumes `publish` and `post_draft` jobs. Also runs an aiogram dispatcher for inline button callbacks and admin commands.

**`post_draft` job:** posts a draft card to the editor supergroup with four inline buttons: ✅ Approve, 🗑 Reject, 🏷 Edit tags, 🗓 Schedule.

**`publish` job:**

1. Sets `state=publishing`.
2. Pre-inserts a `published_dedupe` row (`ON CONFLICT DO NOTHING`) as a race guard.
3. Sends the post to the destination channel via the local Bot API server.
4. Marks the post `published` and edits the draft card to "☑️ Published ✓".
5. On failure: deletes the pre-inserted dedupe row (allowing retry), sets `state=publish_failed`, and sends an alert to the editor supergroup.

Consecutive publishes are spaced by `PUBLISH_SPACING_SECONDS`. `TelegramRetryAfter` errors are handled with sleep-and-retry.

**Callback auth:** every inline button press is validated by checking (1) `chat.id == EDITOR_GROUP_ID` and (2) `callback.from_user.id` matches an `Admin` record that is not disabled and has role `>= editor`.

---

### api (FastAPI)

Async FastAPI application using SQLAlchemy 2.0 async + asyncpg.

- **Auth:** HS256 JWT. Access tokens expire after `ACCESS_TOKEN_TTL_MINUTES` (default 30 min). Refresh tokens are stored in an `httpOnly`, `SameSite=Lax` cookie scoped to `/api/auth` and expire after `REFRESH_TOKEN_TTL_DAYS` (default 14 days). The `/auth/login` and `/auth/token` endpoints are rate-limited to 10 requests/minute per IP via slowapi.
- **Roles:** `editor` (read + approve/reject), `admin` (full CRUD), `super_admin` (admin management).
- **Endpoints:** queue management, audit log, CRUD for tags, templates, source channels, and admin users.
- **Passwords:** hashed with Argon2 (argon2-cffi); automatically rehashed on login if the stored parameters are outdated.
- **Health:** `GET /healthz` on port 8000.

---

### web (Next.js 14 + React 18 + Tailwind CSS)

Back-office UI. Communicates with the API via Next.js API routes (server-side) and direct fetch calls (client-side using `NEXT_PUBLIC_API_URL`). Access token refresh is transparent via the `httpOnly` refresh cookie.

---

### postgres (PostgreSQL 16)

Primary relational store. Holds posts, tags, templates, source channels, admins, audit events, and dedupe records.

---

### redis (Redis 7)

ARQ job queue. Also used for delayed publish jobs (scheduled posts).

---

### botapi (Official Telegram Bot API local server)

Runs the official Telegram Bot API server locally. Bypasses the 50 MB cloud upload limit, allowing media up to 2 GiB. The bot service sends all Telegram API calls through this local server.

---

### caddy (Caddy 2)

Reverse proxy with automatic TLS. Routes public HTTPS traffic to the `api` and `web` services.

---

## Data Flow

```
Source channel (Telegram)
        │
        ▼
[1] userbot detects NewMessage
        │
        ▼
[2] Insert Post row (state=pending, raw_media_refs=[])
        │
        ▼
[3] Download media → update raw_media_refs
        │
        ▼
[4] Enqueue normalize → QUEUE_WORKER
        │
        ▼
[5] worker: normalize job
    ├── render normalized_text
    ├── compute dedupe_hash
    ├── check published_dedupe
    │     └── duplicate found → state=rejected (stop)
    └── route by channel mode
          ├── auto   → enqueue publish → QUEUE_BOT
          └── queue  → enqueue post_draft → QUEUE_BOT
                            │
                            ▼
[6] bot: post_draft → draft card in editor supergroup
                            │
                    Editor action (button or web UI)
                            │
          ┌─────────────────┼─────────────────┐
        Approve           Reject           Schedule
          │                 │                 │
          ▼                 ▼                 ▼
    publish job        state=rejected    state=scheduled
    enqueued           (terminal)        (ARQ delayed job)
          │
          ▼
[7] bot: publish job
    (a) state=publishing
    (b) pre-insert published_dedupe row
    (c) send to destination channel
    (d) state=published
    (e) edit draft card → "☑️ Published ✓"
```

---

## Post State Machine

```
pending
  │
  ├─[normalize, duplicate]──────────────────► rejected  (terminal)
  │
  ├─[normalize, auto channel]──► approved
  │                                  │
  │                                  ├─[publish]──► publishing ──► published  (terminal)
  │                                  │                         └──► publish_failed
  │                                  │
  │                                  └─[schedule action]──► scheduled
  │                                                              │
  │                                                    [ARQ delayed job / reconcile]
  │                                                              │
  │                                                         (re-enqueue publish)
  │
  ├─[normalize, queue channel]──► post_draft sent
  │                                  │
  │                         Editor approves / rejects
  │                                  │
  │                      (same branches as auto above)
  │
  └─[reject button / web]──────────────────► rejected  (terminal)
```

**Notes:**

- `normalize` does not change the state from `pending`; the state remains `pending` until an explicit approve, reject, or schedule action.
- `publishing` is a short-lived intermediate state set immediately before the Telegram send to prevent double-publish on crash/retry.
- `publish_failed` posts can be retried by ARQ backoff or by manually returning them to `approved` state.

---

## Dedupe

### Hash computation

```
dedupe_hash = SHA256(text_fingerprint(raw_text) + ":" + media_fingerprint(raw_media_refs))
```

**`text_fingerprint(raw_text)`:**
1. Normalize whitespace (collapse runs, strip leading/trailing).
2. Lowercase.
3. SHA256 hex digest.

**`media_fingerprint(raw_media_refs)`:**
1. Sort refs by `(type, size)`.
2. For each ref, format as `type:size:mime`.
3. Join with `|`.
4. SHA256 hex digest.

### Lookback window

Controlled by `DEDUPE_LOOKBACK_DAYS` (default: 7). Only `published_dedupe` rows within this window are checked.

### When it is checked

- **At normalize time** — primary duplicate rejection.
- **At publish time** — race guard. If a duplicate row already exists when the publish job runs, the job calls `_mark_duplicate` instead of sending to Telegram.

### What is hashed

The hash is computed from `raw_text` and `raw_media_refs`, not from `normalized_text`. Changing a Jinja2 template does not cause previously published content to be treated as new.

---

## Double-Publish Guard

The system uses two complementary mechanisms to ensure a post is never sent to Telegram more than once:

1. **`publishing` state** — set before the Telegram API call. If the process crashes and restarts, the post is already in `publishing`, preventing a naive re-send.
2. **`published_dedupe` pre-reservation** — a row is inserted (`ON CONFLICT DO NOTHING`) before the Telegram send:
   - If the send **succeeds**: `_mark_published` completes normally. The dedupe row stays.
   - If the send **fails**: the dedupe row is deleted so the job can be retried cleanly.
   - If `_mark_published` **fails after a successful send**: the dedupe row is already present. On retry, the publish job detects the existing dedupe row and calls `_mark_duplicate` instead of re-sending.

---

## Security

| Concern | Implementation |
|---|---|
| Password storage | Argon2 (argon2-cffi); rehashed automatically on login if parameters changed |
| JWT signing | HS256 with `JWT_SECRET`; startup fails fast if secret is empty or a placeholder |
| Refresh token | `httpOnly`, `SameSite=Lax`, `Secure=true` in production; scoped to `/api/auth` |
| Auth rate limiting | 10 req/min per IP on `/auth/login` and `/auth/token` (slowapi) |
| Bot callback auth | `chat.id == EDITOR_GROUP_ID` AND `from_user.id` matches a non-disabled Admin with role `>= editor` |
| CORS | `CORS_ORIGINS` — wildcard disables `allow_credentials`; set explicitly in production |

---

## Cross-Cutting Concerns

### Structured logging

All services emit structured JSON logs via `structlog`. Every log event is tagged with the service name.

### Health endpoints

| Service | Port | Path |
|---|---|---|
| api | 8000 | `/healthz` |
| bot | 8082 | `/healthz` |
| worker | 8083 | `/healthz` |
| userbot | 8084 | `/healthz` |

All four endpoints are probed by Docker healthchecks.

### ARQ connection pool

A process-wide shared ARQ pool is used by each service. The pool is automatically recreated on `ConnectionError`.

### Shared volumes

| Volume | Writer | Reader |
|---|---|---|
| Media volume | userbot (download) | bot (publish) |
| Session volume | userbot | worker (Telethon `.session` file) |
