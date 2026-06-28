---
title: "Source Channels API"
description: "Register and manage Telegram source channels for post ingestion"
api_version: "v1"
---

# Source Channels API

Source channels are Telegram channels whose posts the userbot monitors and
ingests. Each channel carries ingestion settings, a publication policy, default
tags, and an optional normalization template. Channels are managed under the
`/api/source-channels` prefix.

> **Userbot restart required.** After adding or deleting a source channel you
> must restart the userbot process so it subscribes to (or unsubscribes from)
> the channel on Telegram.

## Authentication and roles

Role hierarchy (lowest to highest): `editor` < `admin` < `super_admin`. A role
grants access to everything at or below it in the hierarchy.

| Endpoint | Minimum role |
|---|---|
| `GET /api/source-channels` | `editor` |
| `POST /api/source-channels` | `admin` |
| `PATCH /api/source-channels/{channel_id}` | `admin` |
| `DELETE /api/source-channels/{channel_id}` | `admin` |

---

## Publication policies

| Value | Behavior |
|---|---|
| `"auto"` | Posts are published immediately after normalization; no human review |
| `"queue"` | Posts land as draft cards in the editor supergroup and the web queue, awaiting approval |

---

## Data model — SourceChannelOut

All endpoints that return a source channel return the following object.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `telegram_channel_id` | integer | Telegram's internal channel ID |
| `title` | string | Display title; max 256 characters |
| `username` | string \| null | Public Telegram username (without `@`), if any |
| `ingestion_enabled` | boolean | When `false`, new posts from this channel are ignored |
| `policy` | `"auto"` \| `"queue"` | Publication policy (see above) |
| `default_tag_ids` | integer[] | Tag IDs automatically applied to every ingested post |
| `normalization_template_id` | integer \| null | FK to a template; `null` means no normalization |
| `max_media_size_bytes` | integer \| null | Media files larger than this are dropped |
| `source_label` | string \| null | Label used as `{{ source }}` in templates (falls back to `username`, then `title`) |
| `created_at` | datetime (ISO 8601) | Creation timestamp |

---

## Endpoints

### GET /api/source-channels

Returns all source channels ordered alphabetically by `title`.

**Auth:** `editor` or higher.

**Request:** no body, no query parameters.

**Response `200`**

```json
[
  {
    "id": 1,
    "telegram_channel_id": -1001234567890,
    "title": "World News",
    "username": "worldnews",
    "ingestion_enabled": true,
    "policy": "queue",
    "default_tag_ids": [2, 5],
    "normalization_template_id": 1,
    "max_media_size_bytes": 2147483648,
    "source_label": "World News",
    "created_at": "2024-01-15T09:00:00Z"
  }
]
```

**Errors:** `401` if unauthenticated, `403` if insufficient role.

**Example**

```bash
curl -X GET https://example.com/api/source-channels \
  -H "Authorization: Bearer <token>"
```

---

### POST /api/source-channels

Registers a new source channel.

**Auth:** `admin` or higher.

**Request body**

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `telegram_channel_id` | integer | yes | — | Telegram's internal channel ID |
| `title` | string | yes | — | Max 256 characters |
| `username` | string \| null | no | `null` | Public username without `@` |
| `ingestion_enabled` | boolean | no | `true` | Set to `false` to pause ingestion without deleting |
| `policy` | `"auto"` \| `"queue"` | yes | — | Publication policy |
| `default_tag_ids` | integer[] | no | `[]` | Tags auto-applied to every ingested post |
| `normalization_template_id` | integer \| null | no | `null` | FK to a template |
| `max_media_size_bytes` | integer \| null | no | `MEDIA_MAX_SIZE_DEFAULT` (2 GiB) | Drop media files larger than this; `null` uses the server default |
| `source_label` | string \| null | no | `null` | Overrides `{{ source }}` in templates |

```json
{
  "telegram_channel_id": -1001234567890,
  "title": "World News",
  "username": "worldnews",
  "ingestion_enabled": true,
  "policy": "queue",
  "default_tag_ids": [2, 5],
  "normalization_template_id": 1,
  "max_media_size_bytes": null,
  "source_label": "World News"
}
```

**Response `201`** — the created `SourceChannelOut`.

**Errors**

| Status | Condition |
|---|---|
| `409` | A channel with that `telegram_channel_id` is already registered |
| `400` | Missing required field or validation failure |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X POST https://example.com/api/source-channels \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "telegram_channel_id": -1001234567890,
    "title": "World News",
    "username": "worldnews",
    "policy": "queue",
    "default_tag_ids": [2, 5],
    "normalization_template_id": 1
  }'
```

---

### PATCH /api/source-channels/{channel_id}

Updates settings for an existing source channel. `telegram_channel_id` is
immutable after creation and cannot be changed via this endpoint.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `channel_id` | integer | ID of the source channel to update |

**Request body** — any subset of the create fields except `telegram_channel_id`.
All fields are optional; omit any field to leave it unchanged.

| Field | Type | Notes |
|---|---|---|
| `title` | string | Max 256 characters |
| `username` | string \| null | Public username without `@` |
| `ingestion_enabled` | boolean | Pause or resume ingestion |
| `policy` | `"auto"` \| `"queue"` | Publication policy |
| `default_tag_ids` | integer[] | Replaces the entire list |
| `normalization_template_id` | integer \| null | Set to `null` to remove the template |
| `max_media_size_bytes` | integer \| null | Override media size limit |
| `source_label` | string \| null | Override `{{ source }}` in templates |

```json
{
  "ingestion_enabled": false,
  "policy": "auto"
}
```

**Response `200`** — the updated `SourceChannelOut`.

**Errors**

| Status | Condition |
|---|---|
| `404` | No channel with that `channel_id` |
| `400` | Validation failure |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X PATCH https://example.com/api/source-channels/1 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"ingestion_enabled": false}'
```

---

### DELETE /api/source-channels/{channel_id}

Deletes a source channel and all of its posts.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `channel_id` | integer | ID of the source channel to delete |

**Pre-flight check:** the request is rejected with `409` if the channel has any
posts in a non-terminal state (i.e., not `published` or `rejected`). The response
body includes the count of blocking posts and a message instructing the operator
to reject or wait for them to complete before retrying.

```json
{
  "detail": "Channel has 3 post(s) in non-terminal states. Reject or wait for them to complete before deleting."
}
```

**Side effects on success:** all posts belonging to the channel — and their
associated events — are cascade-deleted.

**Response `204`** — no body.

> **Userbot restart required.** After a successful delete, restart the userbot so
> it unsubscribes from the Telegram channel.

**Errors**

| Status | Condition |
|---|---|
| `409` | Channel has posts in non-terminal states (response includes count and guidance) |
| `404` | No channel with that `channel_id` |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X DELETE https://example.com/api/source-channels/1 \
  -H "Authorization: Bearer <token>"
```
