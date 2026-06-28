---
title: "Audit API"
description: "Query the post event audit log"
api_version: "v1"
---

# Audit API

All endpoints are mounted under `/api/audit`. They provide read-only access to the audit log, which records every significant action taken on a post throughout its lifecycle. Every endpoint requires a valid Bearer access token; any role (`editor`, `admin`, `super_admin`) is permitted.

---

## Authentication

All endpoints require:

```
Authorization: Bearer <access_token>
```

Requests without a valid token return HTTP 401.

---

## EventAction Values

| Value            | Recorded when                                                    |
|------------------|------------------------------------------------------------------|
| `ingested`       | Post received from a Telegram channel and stored                 |
| `edited`         | Tags updated via `PATCH /api/queue/{post_id}/tags`               |
| `approved`       | Post approved (publish job enqueued immediately)                 |
| `rejected`       | Post rejected by a moderator                                     |
| `scheduled`      | Post scheduled for future publication                            |
| `published`      | Post successfully published to the destination channel           |
| `publish_failed` | Publish job exhausted all retries without success                |
| `duplicate`      | Post detected as a duplicate of an already-ingested post         |
| `media_omitted`  | Media attachment was dropped during normalisation                |
| `draft_posted`   | Draft version of the post was sent (e.g. for preview)           |

---

## Schemas

### PostEventOut

```json
{
  "id":             "int",
  "post_id":        "int",
  "actor_admin_id": "int | null",
  "action":         "EventAction",
  "payload":        "any | null",
  "created_at":     "datetime (UTC ISO-8601)"
}
```

`actor_admin_id` is `null` for system-generated events (e.g. `ingested`, `published`, `publish_failed`).

### Paginated Response

`GET /api/audit` returns:

```json
{
  "items":  "PostEventOut[]",
  "total":  "int",
  "limit":  "int",
  "offset": "int"
}
```

`GET /api/audit/post/{post_id}` returns a plain array:

```json
"PostEventOut[]"
```

---

## Endpoints

### GET /api/audit

Lists audit events across all posts, ordered by `created_at` descending (most recent first). Supports filtering by post and by action type.

#### Request

```
GET /api/audit
Authorization: Bearer <access_token>
```

Query parameters:

| Parameter | Type        | Default | Max | Description                                                   |
|-----------|-------------|---------|-----|---------------------------------------------------------------|
| `post_id` | int         | —       | —   | Filter events to a single post                                |
| `action`  | EventAction | —       | —   | Filter by action type. Repeatable to match multiple actions   |
| `limit`   | int         | 100     | 500 | Number of results to return                                   |
| `offset`  | int         | 0       | —   | Number of results to skip                                     |

#### Response 200

```json
{
  "items": [
    {
      "id":             301,
      "post_id":        42,
      "actor_admin_id": 1,
      "action":         "approved",
      "payload":        null,
      "created_at":     "2025-06-28T09:15:00Z"
    }
  ],
  "total":  84,
  "limit":  100,
  "offset": 0
}
```

#### curl Examples

```bash
# All recent audit events (first page, default limit of 100)
curl https://example.com/api/audit \
  -H "Authorization: Bearer <access_token>"

# Events for a specific post
curl -G https://example.com/api/audit \
  -H "Authorization: Bearer <access_token>" \
  --data-urlencode "post_id=42"

# Filter to approved and rejected actions across all posts
curl -G https://example.com/api/audit \
  -H "Authorization: Bearer <access_token>" \
  --data-urlencode "action=approved" \
  --data-urlencode "action=rejected" \
  --data-urlencode "limit=50"
```

---

### GET /api/audit/post/{post_id}

Returns the complete, ordered history of events for a single post. Unlike the paginated list endpoint, this returns all events as a plain array ordered by `created_at` ascending, which is useful for rendering a timeline view.

#### Request

```
GET /api/audit/post/{post_id}
Authorization: Bearer <access_token>
```

| Path param | Type | Description    |
|------------|------|----------------|
| `post_id`  | int  | ID of the post |

#### Response 200

A plain array of all events for the post, in chronological order:

```json
[
  {
    "id":             201,
    "post_id":        42,
    "actor_admin_id": null,
    "action":         "ingested",
    "payload":        null,
    "created_at":     "2025-06-28T08:00:00Z"
  },
  {
    "id":             205,
    "post_id":        42,
    "actor_admin_id": 1,
    "action":         "edited",
    "payload":        null,
    "created_at":     "2025-06-28T08:45:00Z"
  },
  {
    "id":             301,
    "post_id":        42,
    "actor_admin_id": 1,
    "action":         "approved",
    "payload":        null,
    "created_at":     "2025-06-28T09:15:00Z"
  },
  {
    "id":             412,
    "post_id":        42,
    "actor_admin_id": null,
    "action":         "published",
    "payload":        null,
    "created_at":     "2025-06-28T09:15:44Z"
  }
]
```

#### curl Example

```bash
curl https://example.com/api/audit/post/42 \
  -H "Authorization: Bearer <access_token>"
```
