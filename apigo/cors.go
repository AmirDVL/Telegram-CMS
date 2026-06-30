package main

import "net/http"

// corsMiddleware mirrors the FastAPI CORSMiddleware config in api/main.py:
// allow-list ⇒ credentials enabled; "*" ⇒ credentials disabled; allowed headers
// are Authorization, Content-Type, Cookie.
func (a *App) corsMiddleware(next http.Handler) http.Handler {
	origins := a.cfg.CORSList()
	allowAll := len(origins) == 1 && origins[0] == "*"
	allowCredentials := !allowAll
	allowSet := make(map[string]bool, len(origins))
	for _, o := range origins {
		allowSet[o] = true
	}
	const allowMethods = "DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT"
	const allowHeaders = "Authorization, Content-Type, Cookie"

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if origin != "" {
			allowedOrigin := ""
			if allowAll {
				allowedOrigin = "*"
			} else if allowSet[origin] {
				allowedOrigin = origin
			}
			if allowedOrigin != "" {
				h := w.Header()
				h.Set("Access-Control-Allow-Origin", allowedOrigin)
				if allowCredentials {
					h.Set("Access-Control-Allow-Credentials", "true")
				}
				if allowedOrigin != "*" {
					h.Add("Vary", "Origin")
				}
			}
			if r.Method == http.MethodOptions && r.Header.Get("Access-Control-Request-Method") != "" {
				h := w.Header()
				h.Set("Access-Control-Allow-Methods", allowMethods)
				if rh := r.Header.Get("Access-Control-Request-Headers"); rh != "" {
					h.Set("Access-Control-Allow-Headers", rh)
				} else {
					h.Set("Access-Control-Allow-Headers", allowHeaders)
				}
				h.Set("Access-Control-Max-Age", "600")
				w.WriteHeader(http.StatusOK)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}
