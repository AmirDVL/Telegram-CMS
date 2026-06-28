---
title: "Queue API"
description: "Browse, tag, and action posts in the moderation queue"
api_version: "v1"
---

# Queue API

All endpoints are mounted under `/api/queue` and manage the lifecycle of posts received from Telegram channels. Every endpoint requires a valid Bearer access token; any role (`editor`, `admin`, `super_admin`) is permitted.

---

## Authentication

All endpoints require:

```
Authorization: Bearer <access_token>
```

Requests without a valid token return HTTP 401.

---

## Post Lifecycle

A post moves through the following states:

| State           | Description                                              |
|-----------------|----------------------------------------------------------|
| `pending`       | Received from Telegram, awaiting moderation              |
| `approved`      | Approved; publish job enqueued for immediate execution   |
| `scheduled`     | Approved for future publication at a specific time       |
| `publishing`    | Publish job is actively running                          |
| `published`     | Successfully published to the destination channel        |
| `rejected`      | Rejected by a moderator                                  |
| `publish_failed`| Publish job failed after all retries                     |

---

## Audit Logging

All decision endpoints (`/decision`, `/approve`, `/schedule`, `/reject`) and the tag-edit endpoint (`PATCH /tags`) append a `post_event` record to the audit log, capturing the `actor_admin_id` of the authenticated user who performed the action. See [audit.md](audit.md) for how to query these events.

---

## Schemas

### PostOut

```json
{
  "id":                   "int",
  "source_channel_id":    "int",
  "source_message_id":    "int",
  "raw_text":             "string | null",
  "raw_media_refs":       "any | null",
  "received_at":          "datetime (UTC ISO-8601)",
  "state":                "PostState",
  "normalized_text":      "string | null",
  "media_paths":          "string[] | null",
  "tag_ids":              "int[]",
  "scheduled_for":        "datetime (UTC ISO-8601) | null",
  "published_message_id": "int | null",
  "published_at":         "datetime (UTC ISO-8601) | null",
  "dedupe_hash":          "string | null",
  "created_at":           "datetime (UTC ISO-8601)",
  "updated_at":           "datetime (UTC ISO-8601)"
}
```

### Paginated Response

All list endpoints return:

```json
{
  "items":  "PostOut[]",
  "total":  "int",
  "limit":  "int",
  "offset": "int"
}
```

---

## Endpoints

### GET /api/queue

Lists posts in the moderation queue. Results are ordered by `received_at` descending (newest first).

#### Request

```
GET /api/queue
Authorization: Bearer <access_token>
```

Query parameters:

| Parameter | Type       | Default | Max | Description                                          |
|-----------|------------|---------|-----|------------------------------------------------------|
| `state`   | PostState  | —       | —   | Filter by state. Repeatable to match multiple states |
| `limit`   | int        | 50      | 200 | Number of results to return                          |
| `offset`  | int        | 0       | —   | Number of results to skip                            |

`state` accepts any of: `pending`, `approved`, `scheduled`, `publishing`, `published`, `rejected`, `publish_failed`.

#### Response 200

```json
{
  "items": [ /* PostOut */ ],
  "total": 142,
  "limit": 50,
  "offset": 0
}
```

#### curl Example

```bash
# Pending and scheduled posts, first page
curl -G https://example.com/api/queue \
  -H "Authorization: Bearer <access_token>" \
  --data-urlencode "state=pending" \
  --data-urlencode "state=scheduled" \
  --data-urlencode "limit=20"
```

---

### GET /api/queue/{post_id}

Retrieves a single post by its ID.

#### Request

```
GET /api/queue/{post_id}
Authorization: Bearer <access_token>
```

| Path param | Type | Description   |
|------------|------|---------------|
| `post_id`  | int  | ID of the post |

#### Response 200

A single `PostOut` object.

#### Response 404

```json
{ "detail": "Post not found" }
```

#### curl Example

```bash
curl https://example.com/api/queue/42 \
  -H "Authorization: Bearer <access_token>"
```

---

### PATCH /api/queue/{post_id}/tags

Replaces the tag set on a post. Appends an `edited` event to the audit log.

#### Request

```
PATCH /api/queue/{post_id}/tags
Authorization: Bearer <access_token>
Content-Type: application/json
```

Body:

```json
{
  "tag_ids": [1, 4, 7]
}
```

| Field     | Type  | Required | Description            |
|-----------|-------|----------|------------------------|
| `tag_ids` | int[] | yes      | Full replacement tag set |

#### Response 200

Updated `PostOut`.

#### curl Example

```bash
curl -X PATCH https://example.com/api/queue/42/tags \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"tag_ids": [1, 4, 7]}'
```

---

### POST /api/queue/{post_id}/decision

The primary decision endpoint. Approves, schedules, or rejects a post, and appends the corresponding event to the audit log.

#### Request

```
POST /api/queue/{post_id}/decision
Authorization: Bearer <access_token>
Content-Type: application/json
```

Body:

```json
{
  "action":        "approve | schedule | reject",
  "tag_ids":       [1, 2] ,
  "scheduled_for": "2025-06-30T14:00:00Z"
}
```

| Field           | Type              | Required             | Description                                           |
|-----------------|-------------------|----------------------|-------------------------------------------------------|
| `action`        | string            | yes                  | One of `approve`, `schedule`, `reject`                |
| `tag_ids`       | int[] \| null     | no                   | Tags to apply before actioning                        |
| `scheduled_for` | datetime \| null  | required for schedule| Future UTC datetime for scheduled publication         |

**Action behaviour:**

- **`approve`** — Sets state to `approved` and immediately enqueues a publish job.
- **`schedule`** — Sets state to `scheduled` and enqueues a delayed publish job at `scheduled_for`. `scheduled_for` must be present and must be a future UTC datetime.
- **`reject`** — Sets state to `rejected`. No publish job is enqueued.

#### Response 200

Updated `PostOut`.

#### Response 400

Returned when:

- `action` is `schedule` but `scheduled_for` is absent.
- `action` is `schedule` but `scheduled_for` is in the past.
- `action` is not one of the three recognised values.

```json
{ "detail": "..." }
```

#### curl Example

```bash
# Approve immediately
curl -X POST https://example.com/api/queue/42/decision \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "approve"}'

# Schedule for a future time
curl -X POST https://example.com/api/queue/42/decision \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "schedule", "scheduled_for": "2025-06-30T14:00:00Z"}'

# Reject
curl -X POST https://example.com/api/queue/42/decision \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"action": "reject"}'
```

---

### POST /api/queue/{post_id}/approve

Shorthand for `POST /decision` with `action=approve`.

#### Request

```
POST /api/queue/{post_id}/approve
Authorization: Bearer <access_token>
Content-Type: application/json
```

Body (optional):

```json
{
  "tag_ids": [1, 2]
}
```

#### Response 200

Updated `PostOut`.

#### curl Example

```bash
curl -X POST https://example.com/api/queue/42/approve \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"tag_ids": [3]}'
```

---

### POST /api/queue/{post_id}/schedule

Shorthand for `POST /decision` with `action=schedule`.

#### Request

```
POST /api/queue/{post_id}/schedule
Authorization: Bearer <access_token>
Content-Type: application/json
```

Body:

```json
{
  "scheduled_for": "2025-06-30T14:00:00Z"
}
```

| Field           | Type     | Required | Description                          |
|-----------------|----------|----------|--------------------------------------|
| `scheduled_for` | datetime | yes      | Future UTC datetime for publication  |

#### Response 200

Updated `PostOut`.

#### Response 400

`scheduled_for` is absent or in the past.

#### curl Example

```bash
curl -X POST https://example.com/api/queue/42/schedule \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"scheduled_for": "2025-06-30T14:00:00Z"}'
```

---

### POST /api/queue/{post_id}/reject

Shorthand for `POST /decision` with `action=reject`. No request body is required.

#### Request

```
POST /api/queue/{post_id}/reject
Authorization: Bearer <access_token>
```

#### Response 200

Updated `PostOut`.

#### curl Example

```bash
curl -X POST https://example.com/api/queue/42/reject \
  -H "Authorization: Bearer <access_token>"
```
