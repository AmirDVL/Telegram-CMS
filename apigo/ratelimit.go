package main

import (
	"net"
	"net/http"
	"strconv"
	"time"
)

func clientIP(r *http.Request) string {
	// Mirrors slowapi's get_remote_address (the direct peer address). Behind a
	// reverse proxy this is the proxy IP — same behaviour as the Python API.
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		return r.RemoteAddr
	}
	return host
}

// rateLimit is a Redis fixed-window limiter mirroring the slowapi "10/minute"
// guard on the auth endpoints. It fails open on Redis errors so auth never
// breaks when the broker is down.
func (a *App) rateLimit(limit int, window time.Duration, bucket string) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			key := "api:ratelimit:" + bucket + ":" + clientIP(r)
			ctx := r.Context()
			n, err := a.rdb.Incr(ctx, key).Result()
			if err == nil {
				if n == 1 {
					a.rdb.Expire(ctx, key, window)
				}
				if n > int64(limit) {
					writeError(w, http.StatusTooManyRequests,
						"Rate limit exceeded: "+strconv.Itoa(limit)+" per 1 minute")
					return
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}
