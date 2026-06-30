package main

import (
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
)

// router wires every endpoint. Routes are served at the root (e.g. /auth/login)
// because Caddy's `handle_path /api/*` strips the /api prefix before proxying —
// matching the Python API, whose root_path="/api" is purely cosmetic.
func (a *App) router() http.Handler {
	r := chi.NewRouter()
	r.Use(a.metricsMiddleware)
	r.Use(a.corsMiddleware)

	// Unauthenticated.
	r.Get("/healthz", a.handleHealthz)
	r.Get("/meta", a.handleMeta)
	r.Get("/metrics", a.handleMetrics)

	// Auth.
	r.With(a.rateLimit(10, time.Minute, "login")).Post("/auth/login", a.handleLoginJSON)
	r.With(a.rateLimit(10, time.Minute, "token")).Post("/auth/token", a.handleLoginForm)
	r.Post("/auth/refresh", a.handleRefresh)
	r.Post("/auth/logout", a.handleLogout)
	r.With(a.requireRole(RoleEditor)).Get("/auth/me", a.handleMe)

	// Tags.
	r.With(a.requireRole(RoleEditor)).Get("/tags", a.handleListTags)
	r.With(a.requireRole(RoleEditor)).Get("/tags/count", a.handleCountTags)
	r.With(a.requireRole(RoleAdmin)).Post("/tags", a.handleCreateTag)
	r.With(a.requireRole(RoleAdmin)).Patch("/tags/{tagID}", a.handleUpdateTag)
	r.With(a.requireRole(RoleAdmin)).Delete("/tags/{tagID}", a.handleDeleteTag)

	// Templates.
	r.With(a.requireRole(RoleEditor)).Get("/templates", a.handleListTemplates)
	r.With(a.requireRole(RoleAdmin)).Post("/templates", a.handleCreateTemplate)
	r.With(a.requireRole(RoleAdmin)).Patch("/templates/{templateID}", a.handleUpdateTemplate)
	r.With(a.requireRole(RoleAdmin)).Delete("/templates/{templateID}", a.handleDeleteTemplate)

	// Source channels.
	r.With(a.requireRole(RoleEditor)).Get("/source-channels", a.handleListChannels)
	r.With(a.requireRole(RoleAdmin)).Post("/source-channels", a.handleCreateChannel)
	r.With(a.requireRole(RoleAdmin)).Patch("/source-channels/{channelID}", a.handleUpdateChannel)
	r.With(a.requireRole(RoleAdmin)).Delete("/source-channels/{channelID}", a.handleDeleteChannel)
	r.With(a.requireRole(RoleEditor)).Get("/source-channels/{channelID}/ai", a.handleGetAISettings)
	r.With(a.requireRole(RoleAdmin)).Patch("/source-channels/{channelID}/ai", a.handleUpdateAISettings)
	r.With(a.requireRole(RoleEditor)).Post("/source-channels/{channelID}/ai/test", a.handleTestAITransform)

	// Admins.
	r.With(a.requireRole(RoleAdmin)).Get("/admins", a.handleListAdmins)
	r.With(a.requireRole(RoleSuperAdmin)).Post("/admins", a.handleCreateAdmin)
	r.With(a.requireRole(RoleSuperAdmin)).Patch("/admins/{adminID}", a.handleUpdateAdmin)

	// Queue (all require a valid admin; editor is the minimum role).
	r.With(a.requireRole(RoleEditor)).Get("/queue", a.handleListQueue)
	r.With(a.requireRole(RoleEditor)).Get("/queue/{postID}", a.handleGetPost)
	r.With(a.requireRole(RoleEditor)).Patch("/queue/{postID}/tags", a.handleEditTags)
	r.With(a.requireRole(RoleEditor)).Post("/queue/{postID}/decision", a.handleDecision)
	r.With(a.requireRole(RoleEditor)).Post("/queue/{postID}/approve", a.handleApprove)
	r.With(a.requireRole(RoleEditor)).Post("/queue/{postID}/schedule", a.handleSchedule)
	r.With(a.requireRole(RoleEditor)).Post("/queue/{postID}/reject", a.handleReject)

	// Audit.
	r.With(a.requireRole(RoleEditor)).Get("/audit", a.handleListEvents)
	r.With(a.requireRole(RoleEditor)).Get("/audit/post/{postID}", a.handleListPostEvents)

	// Tenants (super-admin; each handler also enforces MULTI_TENANCY_ENABLED).
	r.With(a.requireRole(RoleSuperAdmin)).Get("/tenants", a.handleListTenants)
	r.With(a.requireRole(RoleSuperAdmin)).Get("/tenants/{tenantID}", a.handleGetTenant)
	r.With(a.requireRole(RoleSuperAdmin)).Post("/tenants", a.handleCreateTenant)
	r.With(a.requireRole(RoleSuperAdmin)).Patch("/tenants/{tenantID}", a.handleUpdateTenant)
	r.With(a.requireRole(RoleSuperAdmin)).Delete("/tenants/{tenantID}", a.handleDeleteTenant)

	return r
}
