---
title: "Tags API"
description: "Create and manage taxonomy tags; attach them to posts and source channels"
api_version: "v1"
---

# Tags API

Tags are short taxonomy labels (slug + display label + optional color) that can be
attached to posts and source channels. They are managed through the `/api/tags`
prefix.

## Authentication and roles

Role hierarchy (lowest to highest): `editor` < `admin` < `super_admin`. A role
grants access to everything at or below it in the hierarchy.

| Endpoint | Minimum role |
|---|---|
| `GET /api/tags` | `editor` |
| `GET /api/tags/count` | none (public) |
| `POST /api/tags` | `admin` |
| `PATCH /api/tags/{tag_id}` | `admin` |
| `DELETE /api/tags/{tag_id}` | `admin` |

Authenticated requests must supply a valid session token or bearer token as required
by the auth middleware.

---

## Data model — TagOut

All endpoints that return a tag return the following object.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `slug` | string | URL-safe identifier; unique |
| `label` | string | Human-readable display name |
| `color` | string \| null | Arbitrary color string (e.g. hex `#ff0000`) |
| `created_at` | datetime (ISO 8601) | Creation timestamp |

---

## Endpoints

### GET /api/tags

Returns all tags ordered alphabetically by `label`.

**Auth:** `editor` or higher.

**Request:** no body, no query parameters.

**Response `200`**

```json
[
  {
    "id": 1,
    "slug": "breaking-news",
    "label": "Breaking News",
    "color": "#e74c3c",
    "created_at": "2024-01-15T09:00:00Z"
  }
]
```

**Errors:** `401` if unauthenticated, `403` if insufficient role.

**Example**

```bash
curl -X GET https://example.com/api/tags \
  -H "Authorization: Bearer <token>"
```

---

### GET /api/tags/count

Returns the total number of tags in the system. This endpoint requires **no
authentication**.

**Request:** no body, no query parameters.

**Response `200`**

```json
{ "total": 42 }
```

**Example**

```bash
curl -X GET https://example.com/api/tags/count
```

---

### POST /api/tags

Creates a new tag.

**Auth:** `admin` or higher.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `slug` | string | yes | Slugified before storage: lowercased, only `a-z 0-9 -`, max 64 characters. Returns `400` if the value cannot be made valid. |
| `label` | string | yes | Display name shown in the UI |
| `color` | string | no | Any string (e.g. a hex color). Stored as-is. |

```json
{
  "slug": "breaking-news",
  "label": "Breaking News",
  "color": "#e74c3c"
}
```

**Response `201`** — the created `TagOut`.

```json
{
  "id": 7,
  "slug": "breaking-news",
  "label": "Breaking News",
  "color": "#e74c3c",
  "created_at": "2024-06-28T12:00:00Z"
}
```

**Errors**

| Status | Condition |
|---|---|
| `400` | `slug` is empty or cannot be reduced to a valid slug (only `a-z`, `0-9`, `-`; max 64 chars) |
| `409` | A tag with that slug already exists |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X POST https://example.com/api/tags \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"slug": "breaking-news", "label": "Breaking News", "color": "#e74c3c"}'
```

---

### PATCH /api/tags/{tag_id}

Updates the `label` and/or `color` of an existing tag. The `slug` is immutable
after creation.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `tag_id` | integer | ID of the tag to update |

**Request body** — all fields are optional; omit any field to leave it unchanged.

| Field | Type | Notes |
|---|---|---|
| `label` | string | New display name |
| `color` | string \| null | New color string, or `null` to clear |

```json
{
  "label": "Breaking News",
  "color": "#c0392b"
}
```

**Response `200`** — the updated `TagOut`.

```json
{
  "id": 7,
  "slug": "breaking-news",
  "label": "Breaking News",
  "color": "#c0392b",
  "created_at": "2024-06-28T12:00:00Z"
}
```

**Errors**

| Status | Condition |
|---|---|
| `404` | No tag with that `tag_id` |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X PATCH https://example.com/api/tags/7 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"color": "#c0392b"}'
```

---

### DELETE /api/tags/{tag_id}

Deletes a tag and cleans up all references to it.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `tag_id` | integer | ID of the tag to delete |

**Side effects (executed atomically)**

1. The deleted tag's ID is removed from the `tag_ids` array of every post that
   references it (`array_remove`). Posts that do not reference the tag are
   unaffected.
2. All rows in the `source_channel_tags` join table that reference this tag are
   cascade-deleted via the foreign key constraint.

**Response `204`** — no body.

**Errors**

| Status | Condition |
|---|---|
| `404` | No tag with that `tag_id` |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X DELETE https://example.com/api/tags/7 \
  -H "Authorization: Bearer <token>"
```
