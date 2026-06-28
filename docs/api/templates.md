---
title: "Templates API"
description: "Manage Jinja2 normalization templates used to reformat ingested post text"
api_version: "v1"
---

# Templates API

Templates are named Jinja2 template strings applied to raw post text during the
normalization step. Each source channel can reference one template via
`normalization_template_id`. Templates are managed under the `/api/templates`
prefix.

## Authentication and roles

Role hierarchy (lowest to highest): `editor` < `admin` < `super_admin`. A role
grants access to everything at or below it in the hierarchy.

| Endpoint | Minimum role |
|---|---|
| `GET /api/templates` | `editor` |
| `POST /api/templates` | `admin` |
| `PATCH /api/templates/{template_id}` | `admin` |
| `DELETE /api/templates/{template_id}` | `admin` |

---

## Template variables

When a template is rendered, the following variables are available inside the
Jinja2 string.

| Variable | Type | Description |
|---|---|---|
| `{{ text }}` | string | The raw, unmodified text of the ingested post |
| `{{ source }}` | string | The channel's `source_label` if set; otherwise `username`; otherwise `title` |
| `{{ tags }}` | list of strings | Display labels of all tags attached to the post |

**Example template body**

```
**[{{ source }}]** {{ text }}

Tags: {{ tags | join(", ") }}
```

---

## Data model — TemplateOut

All endpoints that return a template return the following object.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `name` | string | Human-readable name; max 128 characters |
| `body` | string | Jinja2 template string |
| `created_at` | datetime (ISO 8601) | Creation timestamp |

---

## Endpoints

### GET /api/templates

Returns all templates ordered alphabetically by `name`.

**Auth:** `editor` or higher.

**Request:** no body, no query parameters.

**Response `200`**

```json
[
  {
    "id": 1,
    "name": "Standard post",
    "body": "**[{{ source }}]** {{ text }}",
    "created_at": "2024-01-15T09:00:00Z"
  }
]
```

**Errors:** `401` if unauthenticated, `403` if insufficient role.

**Example**

```bash
curl -X GET https://example.com/api/templates \
  -H "Authorization: Bearer <token>"
```

---

### POST /api/templates

Creates a new template.

**Auth:** `admin` or higher.

**Request body**

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Max 128 characters |
| `body` | string | yes | Jinja2 template string |

```json
{
  "name": "Standard post",
  "body": "**[{{ source }}]** {{ text }}\n\nTags: {{ tags | join(\", \") }}"
}
```

**Response `201`** — the created `TemplateOut`.

```json
{
  "id": 3,
  "name": "Standard post",
  "body": "**[{{ source }}]** {{ text }}\n\nTags: {{ tags | join(\", \") }}",
  "created_at": "2024-06-28T12:00:00Z"
}
```

**Errors**

| Status | Condition |
|---|---|
| `400` | Missing required field or `name` exceeds 128 characters |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X POST https://example.com/api/templates \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Standard post", "body": "**[{{ source }}]** {{ text }}"}'
```

---

### PATCH /api/templates/{template_id}

Updates the `name` and/or `body` of an existing template.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `template_id` | integer | ID of the template to update |

**Request body** — all fields are optional; omit any field to leave it unchanged.

| Field | Type | Notes |
|---|---|---|
| `name` | string | New name; max 128 characters |
| `body` | string | New Jinja2 template string |

```json
{
  "name": "Compact post",
  "body": "[{{ source }}] {{ text }}"
}
```

**Response `200`** — the updated `TemplateOut`.

```json
{
  "id": 3,
  "name": "Compact post",
  "body": "[{{ source }}] {{ text }}",
  "created_at": "2024-06-28T12:00:00Z"
}
```

**Errors**

| Status | Condition |
|---|---|
| `404` | No template with that `template_id` |
| `400` | `name` exceeds 128 characters |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X PATCH https://example.com/api/templates/3 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Compact post"}'
```

---

### DELETE /api/templates/{template_id}

Deletes a template.

**Auth:** `admin` or higher.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `template_id` | integer | ID of the template to delete |

**Side effect:** any source channel whose `normalization_template_id` references
this template will have that field set to `NULL` automatically (foreign key
`ON DELETE SET NULL`). Those channels will continue to ingest posts, but without
a normalization template applied.

**Response `204`** — no body.

**Errors**

| Status | Condition |
|---|---|
| `404` | No template with that `template_id` |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X DELETE https://example.com/api/templates/3 \
  -H "Authorization: Bearer <token>"
```
