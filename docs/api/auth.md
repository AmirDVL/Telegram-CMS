---
title: "Auth API"
description: "Login, token refresh, logout, and current-user endpoints"
api_version: "v1"
---

# Auth API

All endpoints are mounted under `/api/auth`. They handle JWT-based authentication using short-lived access tokens and rotating httpOnly refresh tokens.

**Access token TTL:** 30 minutes (configured via `ACCESS_TOKEN_MINUTES` env var)  
**Refresh token TTL:** 14 days (configured via `REFRESH_TOKEN_TTL_DAYS` env var)  
**Algorithm:** HS256, signed with `JWT_SECRET` (the server fails fast on startup if this is empty)

---

## Authentication

Most endpoints in this group are public (login, refresh, logout). The single protected endpoint, `GET /api/auth/me`, requires a Bearer access token in the `Authorization` header.

---

## Rate Limiting

`POST /api/auth/login` and `POST /api/auth/token` are rate-limited to **10 requests per minute per IP address**. Exceeding this limit returns HTTP 429.

---

## The `refresh_token` Cookie

On successful login or token refresh the server sets an httpOnly cookie named `refresh_token`:

- **Path:** `/api/auth`
- **HttpOnly:** yes
- **SameSite:** `lax`
- **Secure:** `true` in production, `false` in development

> **CORS note:** If `CORS_ORIGINS` is set to `*` (wildcard), `allow_credentials` is automatically disabled and browsers will not send the cookie cross-origin. Set `CORS_ORIGINS=http://localhost:3000` (or your actual front-end origin) during development so cookie-based refresh works.

---

## Role Values

The `role` field on an admin account is one of:

- `editor`
- `admin`
- `super_admin`

---

## Schemas

### AdminOut

```json
{
  "id":           "int",
  "username":     "string",
  "role":         "editor | admin | super_admin",
  "tg_user_id":  "int | null",
  "created_at":   "datetime (UTC ISO-8601)",
  "disabled_at":  "datetime (UTC ISO-8601) | null"
}
```

---

## Endpoints

### POST /api/auth/login

Authenticates with username + password and returns a JWT pair.

**Rate limit:** 10/min per IP

#### Request

```
POST /api/auth/login
Content-Type: application/json
```

Body:

```json
{
  "username": "alice",
  "password": "s3cr3t"
}
```

#### Response 200

Sets the `refresh_token` httpOnly cookie and returns:

```json
{
  "access_token":  "<jwt>",
  "refresh_token": "<jwt>",
  "token_type":    "bearer"
}
```

#### Response 401

```json
{ "detail": "Incorrect username or password" }
```

#### curl Example

```bash
curl -i -X POST https://example.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "alice", "password": "s3cr3t"}' \
  -c cookies.txt
```

---

### POST /api/auth/token

OAuth2 password-flow endpoint. Identical in behaviour to `/login` but accepts a form body instead of JSON. This endpoint exists so that FastAPI's interactive docs (`/docs`) can issue tokens directly.

**Rate limit:** 10/min per IP

#### Request

```
POST /api/auth/token
Content-Type: application/x-www-form-urlencoded
```

Body fields:

| Field      | Type   | Required |
|------------|--------|----------|
| `username` | string | yes      |
| `password` | string | yes      |

#### Response 200

Same payload and cookie behaviour as `POST /api/auth/login`.

#### curl Example

```bash
curl -i -X POST https://example.com/api/auth/token \
  -F "username=alice" \
  -F "password=s3cr3t" \
  -c cookies.txt
```

---

### POST /api/auth/refresh

Rotates the refresh token. The server reads the refresh token from the httpOnly cookie first; if the cookie is absent it falls back to the `refresh_token` field in the JSON body.

#### Request

```
POST /api/auth/refresh
Content-Type: application/json
```

Body (all fields optional):

```json
{
  "refresh_token": "<jwt or null>"
}
```

#### Response 200

Issues a new access token and refresh token. The `refresh_token` cookie is rotated (old value replaced).

```json
{
  "access_token":  "<new jwt>",
  "refresh_token": "<new jwt>",
  "token_type":    "bearer"
}
```

#### Response 401

Returned when:

- No refresh token is present (neither cookie nor body).
- The token is expired or has an invalid signature.
- The admin account associated with the token has been disabled.

```json
{ "detail": "..." }
```

#### curl Example

```bash
# Using the cookie set during login
curl -i -X POST https://example.com/api/auth/refresh \
  -b cookies.txt \
  -c cookies.txt

# Passing the token explicitly in the body
curl -i -X POST https://example.com/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "<jwt>"}'
```

---

### POST /api/auth/logout

Clears the `refresh_token` cookie. No request body is required.

#### Request

```
POST /api/auth/logout
```

#### Response 204

No body. The `refresh_token` cookie is expired (Max-Age=0).

#### curl Example

```bash
curl -i -X POST https://example.com/api/auth/logout \
  -b cookies.txt \
  -c cookies.txt
```

---

### GET /api/auth/me

Returns the profile of the currently authenticated admin.

**Requires:** `Authorization: Bearer <access_token>`

#### Request

```
GET /api/auth/me
Authorization: Bearer <access_token>
```

#### Response 200

```json
{
  "id":           1,
  "username":     "alice",
  "role":         "admin",
  "tg_user_id":   123456789,
  "created_at":   "2025-01-15T10:00:00Z",
  "disabled_at":  null
}
```

#### Response 401

Returned when the access token is missing, expired, or invalid.

```json
{ "detail": "Not authenticated" }
```

#### curl Example

```bash
curl -i https://example.com/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```
