package main

import (
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
)

func (a *App) handleHealthz(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, HealthOut{Status: "ok", Service: "api"})
}

func (a *App) handleMeta(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]bool{"multi_tenancy_enabled": a.cfg.MultiTenancy})
}

// urlInt64 parses a chi path parameter as int64, returning ok=false on failure
// (the caller responds 404, matching FastAPI's int path-param coercion + 404).
func urlInt64(r *http.Request, key string) (int64, bool) {
	v := chi.URLParam(r, key)
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		return 0, false
	}
	return n, true
}
