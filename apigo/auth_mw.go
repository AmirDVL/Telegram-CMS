package main

import (
	"context"
	"net/http"
	"strings"
)

type ctxKey int

const (
	ctxAdminKey ctxKey = iota
)

func adminFromCtx(r *http.Request) *adminRow {
	a, _ := r.Context().Value(ctxAdminKey).(*adminRow)
	return a
}

func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if h == "" {
		return ""
	}
	parts := strings.SplitN(h, " ", 2)
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		return ""
	}
	return strings.TrimSpace(parts[1])
}

// authenticate decodes the access token and loads the non-disabled admin,
// mirroring api/deps.get_current_admin. Returns an HTTP status code (0 on ok).
func (a *App) authenticate(r *http.Request) (*adminRow, *Claims, int) {
	token := bearerToken(r)
	if token == "" {
		return nil, nil, http.StatusUnauthorized
	}
	claims, err := a.decodeToken(token)
	if err != nil || claims.TokenType != "access" {
		return nil, nil, http.StatusUnauthorized
	}
	admin, err := a.getAdminByID(r.Context(), claims.AdminID)
	if err != nil || admin == nil {
		return nil, nil, http.StatusUnauthorized
	}
	return admin, claims, 0
}

// requireRole returns middleware enforcing role >= min and stashing the admin +
// claims in the request context for handlers to read.
func (a *App) requireRole(min Role) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			admin, _, code := a.authenticate(r)
			if code != 0 {
				writeError(w, code, "Could not validate credentials")
				return
			}
			if !roleAtLeast(Role(admin.Role), min) {
				writeError(w, http.StatusForbidden, "insufficient role")
				return
			}
			ctx := context.WithValue(r.Context(), ctxAdminKey, admin)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}
