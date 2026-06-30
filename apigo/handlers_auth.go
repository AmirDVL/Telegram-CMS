package main

import (
	"context"
	"net/http"
)

const refreshCookieName = "refresh_token"

func (a *App) tokensFor(admin *adminRow) (TokenOut, error) {
	at, err := a.createAccessToken(admin.ID, admin.Username, Role(admin.Role), admin.TenantID)
	if err != nil {
		return TokenOut{}, err
	}
	rt, err := a.createRefreshToken(admin.ID, admin.Username, Role(admin.Role), admin.TenantID)
	if err != nil {
		return TokenOut{}, err
	}
	return TokenOut{AccessToken: at, RefreshToken: rt, TokenType: "bearer"}, nil
}

func (a *App) setRefreshCookie(w http.ResponseWriter, token string) {
	http.SetCookie(w, &http.Cookie{
		Name:     refreshCookieName,
		Value:    token,
		Path:     "/api/auth", // public path the browser sees (Caddy strips /api inbound)
		HttpOnly: true,
		Secure:   a.cfg.IsProduction(),
		SameSite: http.SameSiteLaxMode,
		MaxAge:   a.cfg.RefreshTTLDays * 86400,
	})
}

func (a *App) clearRefreshCookie(w http.ResponseWriter) {
	http.SetCookie(w, &http.Cookie{
		Name:     refreshCookieName,
		Value:    "",
		Path:     "/api/auth",
		HttpOnly: true,
		MaxAge:   -1,
	})
}

// authenticateLogin mirrors api/auth._authenticate (verify + would-rehash).
func (a *App) authenticateLogin(ctx context.Context, username, password string) (*adminRow, bool) {
	row := a.db.QueryRow(ctx,
		`SELECT `+adminCols+` FROM admins WHERE username=$1 AND disabled_at IS NULL`, username)
	admin, err := scanAdmin(row)
	if err != nil {
		// No such (active) user, or a scan/DB error — both yield 401.
		return nil, false
	}
	if !verifyPassword(password, admin.PasswordHash) {
		return nil, false
	}
	return admin, true
}

func (a *App) handleLoginJSON(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Username string `json:"username"`
		Password string `json:"password"`
	}
	if err := decodeJSON(r, &in); err != nil || in.Username == "" || in.Password == "" {
		writeError(w, http.StatusUnprocessableEntity, "username and password are required")
		return
	}
	admin, ok := a.authenticateLogin(r.Context(), in.Username, in.Password)
	if !ok {
		writeError(w, http.StatusUnauthorized, "Incorrect username or password")
		return
	}
	tokens, err := a.tokensFor(admin)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "token error")
		return
	}
	a.setRefreshCookie(w, tokens.RefreshToken)
	writeJSON(w, http.StatusOK, tokens)
}

func (a *App) handleLoginForm(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid form")
		return
	}
	username := r.PostFormValue("username")
	password := r.PostFormValue("password")
	if username == "" || password == "" {
		writeError(w, http.StatusUnprocessableEntity, "username and password are required")
		return
	}
	admin, ok := a.authenticateLogin(r.Context(), username, password)
	if !ok {
		writeError(w, http.StatusUnauthorized, "Incorrect username or password")
		return
	}
	tokens, err := a.tokensFor(admin)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "token error")
		return
	}
	a.setRefreshCookie(w, tokens.RefreshToken)
	writeJSON(w, http.StatusOK, tokens)
}

func (a *App) handleRefresh(w http.ResponseWriter, r *http.Request) {
	token := ""
	if c, err := r.Cookie(refreshCookieName); err == nil {
		token = c.Value
	}
	if token == "" {
		var body struct {
			RefreshToken *string `json:"refresh_token"`
		}
		_ = decodeJSON(r, &body)
		if body.RefreshToken != nil {
			token = *body.RefreshToken
		}
	}
	if token == "" {
		writeError(w, http.StatusUnauthorized, "missing refresh token")
		return
	}
	claims, err := a.decodeToken(token)
	if err != nil || claims.TokenType != "refresh" {
		writeError(w, http.StatusUnauthorized, "invalid refresh token")
		return
	}
	admin, err := a.getAdminByID(r.Context(), claims.AdminID)
	if err != nil || admin == nil {
		writeError(w, http.StatusUnauthorized, "admin not found")
		return
	}
	tokens, err := a.tokensFor(admin)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "token error")
		return
	}
	a.setRefreshCookie(w, tokens.RefreshToken)
	writeJSON(w, http.StatusOK, tokens)
}

func (a *App) handleLogout(w http.ResponseWriter, r *http.Request) {
	a.clearRefreshCookie(w)
	writeNoContent(w)
}

func (a *App) handleMe(w http.ResponseWriter, r *http.Request) {
	admin := adminFromCtx(r)
	writeJSON(w, http.StatusOK, admin.DTO())
}
