---
title: "Admins API"
description: "Create and manage admin accounts and their roles"
api_version: "v1"
---

# Admins API

Admin accounts represent people who can access the web interface and/or the
Telegram editor supergroup. Each account has a role, optional Telegram user ID
for bot interaction, and a disabled flag. Accounts are managed under the
`/api/admins` prefix.

## Authentication and roles

Role hierarchy (lowest to highest): `editor` < `admin` < `super_admin`. A role
grants access to everything at or below it in the hierarchy.

| Endpoint | Minimum role |
|---|---|
| `GET /api/admins` | `admin` |
| `POST /api/admins` | `super_admin` |
| `PATCH /api/admins/{admin_id}` | `super_admin` |

Passwords are hashed with **Argon2** and never returned by any endpoint.

### Initial super-admin

The first super-admin is created via the `seed-admin` CLI command. It reads the
`SEED_ADMIN_USERNAME` environment variable (default: `"admin"`) and
`SEED_ADMIN_PASSWORD` for credentials.

---

## Bot access

Admins who need to use the ✅ **Approve** / 🗑 **Reject** inline buttons in the
Telegram editor supergroup must have their `tg_user_id` set. Without it the bot
cannot map button presses back to an authorized admin.

To find a Telegram user ID, have the admin message [@userinfobot](https://t.me/userinfobot)
or a similar utility bot.

---

## Data model — AdminOut

All endpoints that return an admin return the following object. Passwords are
never included.

| Field | Type | Notes |
|---|---|---|
| `id` | integer | Primary key |
| `username` | string | Unique login name |
| `role` | `"editor"` \| `"admin"` \| `"super_admin"` | Assigned role |
| `tg_user_id` | integer \| null | Telegram user ID for bot inline-button access |
| `created_at` | datetime (ISO 8601) | Account creation timestamp |
| `disabled_at` | datetime (ISO 8601) \| null | Set when the account is disabled; `null` if active |

---

## Endpoints

### GET /api/admins

Returns all admin accounts ordered alphabetically by `username`.

**Auth:** `admin` or higher.

**Request:** no body, no query parameters.

**Response `200`**

```json
[
  {
    "id": 1,
    "username": "alice",
    "role": "super_admin",
    "tg_user_id": 123456789,
    "created_at": "2024-01-01T00:00:00Z",
    "disabled_at": null
  },
  {
    "id": 2,
    "username": "bob",
    "role": "editor",
    "tg_user_id": null,
    "created_at": "2024-03-10T08:30:00Z",
    "disabled_at": "2024-05-01T12:00:00Z"
  }
]
```

**Errors:** `401` if unauthenticated, `403` if insufficient role.

**Example**

```bash
curl -X GET https://example.com/api/admins \
  -H "Authorization: Bearer <token>"
```

---

### POST /api/admins

Creates a new admin account.

**Auth:** `super_admin` only.

**Request body**

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `username` | string | yes | — | 3–64 characters; must be unique |
| `password` | string | yes | — | 8–128 characters; hashed with Argon2 before storage |
| `role` | `"editor"` \| `"admin"` \| `"super_admin"` | no | `"editor"` | Role assigned to the new account |
| `tg_user_id` | integer \| null | no | `null` | Telegram user ID; required for bot inline-button access |

```json
{
  "username": "carol",
  "password": "s3cur3P@ssw0rd",
  "role": "admin",
  "tg_user_id": 987654321
}
```

**Response `201`** — the created `AdminOut` (no password field).

```json
{
  "id": 3,
  "username": "carol",
  "role": "admin",
  "tg_user_id": 987654321,
  "created_at": "2024-06-28T12:00:00Z",
  "disabled_at": null
}
```

**Errors**

| Status | Condition |
|---|---|
| `409` | Username is already taken |
| `400` | Validation failure (e.g. username too short, password too short) |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X POST https://example.com/api/admins \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "carol",
    "password": "s3cur3P@ssw0rd",
    "role": "admin",
    "tg_user_id": 987654321
  }'
```

---

### PATCH /api/admins/{admin_id}

Updates an existing admin account. Username is immutable.

**Auth:** `super_admin` only.

**Path parameter**

| Parameter | Type | Description |
|---|---|---|
| `admin_id` | integer | ID of the admin to update |

**Request body** — all fields are optional; omit any field to leave it unchanged.

| Field | Type | Notes |
|---|---|---|
| `password` | string | New password (8–128 chars); hashed with Argon2 |
| `role` | `"editor"` \| `"admin"` \| `"super_admin"` | New role |
| `disabled` | boolean | `true` sets `disabled_at` to now; `false` clears it |
| `tg_user_id` | integer \| null | Update or clear the Telegram user ID |

```json
{
  "role": "editor",
  "disabled": false,
  "tg_user_id": 111222333
}
```

**Guards**

The server rejects requests that would leave the system with no active
`super_admin`:

- You cannot demote the last active `super_admin` to a lower role.
- You cannot disable the last active `super_admin`.

Both cases return `400` with an explanatory message.

**`disabled` flag behavior**

| Value | Effect on `disabled_at` |
|---|---|
| `true` | Set to the current UTC timestamp |
| `false` | Cleared (`null`); account becomes active |

**Response `200`** — the updated `AdminOut`.

```json
{
  "id": 2,
  "username": "bob",
  "role": "editor",
  "tg_user_id": 111222333,
  "created_at": "2024-03-10T08:30:00Z",
  "disabled_at": null
}
```

**Errors**

| Status | Condition |
|---|---|
| `400` | Would demote or disable the last active `super_admin`, or validation failure |
| `404` | No admin with that `admin_id` |
| `401` / `403` | Unauthenticated or insufficient role |

**Example**

```bash
curl -X PATCH https://example.com/api/admins/2 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"disabled": true}'
```
