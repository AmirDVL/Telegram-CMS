# Back-office API Reference

The back-office API is a FastAPI application served at `/api` (via Caddy at
`https://<APP_DOMAIN>/api`). An interactive OpenAPI UI is available at
`/api/docs` (Swagger UI).

## Base URL

```
https://<APP_DOMAIN>/api
# Development (direct):
http://localhost:8000/api
```

## Authentication

All endpoints except `/api/auth/login`, `/api/auth/token`, `/api/auth/refresh`,
`/api/healthz`, and `GET /api/tags/count` require a **Bearer access token**:

```
Authorization: Bearer <access_token>
```

Obtain a token via [`POST /api/auth/login`](auth.md). Access tokens expire after
30 minutes (configurable via `ACCESS_TOKEN_TTL_MINUTES`). Use
[`POST /api/auth/refresh`](auth.md) with the `refresh_token` httpOnly cookie to
get a new pair without re-entering credentials.

## Role hierarchy

| Role | Permissions |
|---|---|
| `editor` | Read all resources, approve/reject/schedule posts |
| `admin` | All editor permissions + create/update/delete tags, templates, channels |
| `super_admin` | All admin permissions + create/update/delete admin accounts |

A higher role includes all permissions of lower roles.

## Rate limiting

`POST /api/auth/login` and `POST /api/auth/token` are rate-limited to
**10 requests per minute per IP** (HTTP 429 on excess).

## Common response shapes

### Paginated response
```json
{
  "items": [...],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

### Error response
```json
{ "detail": "human-readable message" }
```

## Endpoint groups

| Group | Prefix | Reference |
|---|---|---|
| Auth | `/api/auth` | [auth.md](auth.md) |
| Queue | `/api/queue` | [queue.md](queue.md) |
| Tags | `/api/tags` | [tags.md](tags.md) |
| Templates | `/api/templates` | [templates.md](templates.md) |
| Source channels | `/api/source-channels` | [source-channels.md](source-channels.md) |
| Admins | `/api/admins` | [admins.md](admins.md) |
| Audit log | `/api/audit` | [audit.md](audit.md) |
| Health | `/api/healthz` | — |

## Health check

```
GET /api/healthz
```

Response 200:

```json
{ "status": "ok", "service": "api" }
```

No authentication required. Probed by Docker healthcheck every 15 seconds.
