package main

import (
	"net/http"
	"strconv"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/collectors"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Mirrors api/metrics.py: three families + the default Go runtime/process
// collectors. Names and label sets match the Python API.
type metricsBundle struct {
	reg        *prometheus.Registry
	requests   *prometheus.CounterVec
	latency    *prometheus.HistogramVec
	queueDepth *prometheus.GaugeVec
	handler    http.Handler
}

var metricsExempt = map[string]bool{
	"/metrics":              true,
	"/healthz":              true,
	"/openapi.json":         true,
	"/docs":                 true,
	"/docs/oauth2-redirect": true,
}

func newMetrics() *metricsBundle {
	reg := prometheus.NewRegistry()
	requests := prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "api_http_requests_total",
		Help: "Total HTTP requests handled by the API",
	}, []string{"method", "route", "status"})
	latency := prometheus.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "api_http_request_duration_seconds",
		Help:    "HTTP request latency in seconds",
		Buckets: prometheus.DefBuckets,
	}, []string{"method", "route"})
	queueDepth := prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "arq_queue_depth",
		Help: "ARQ jobs awaiting pickup per queue",
	}, []string{"queue"})
	reg.MustRegister(
		requests, latency, queueDepth,
		collectors.NewGoCollector(),
		collectors.NewProcessCollector(collectors.ProcessCollectorOpts{}),
	)
	return &metricsBundle{
		reg: reg, requests: requests, latency: latency, queueDepth: queueDepth,
		handler: promhttp.HandlerFor(reg, promhttp.HandlerOpts{}),
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
	wrote  bool
}

func (s *statusRecorder) WriteHeader(code int) {
	if !s.wrote {
		s.status = code
		s.wrote = true
	}
	s.ResponseWriter.WriteHeader(code)
}

func (s *statusRecorder) Write(b []byte) (int, error) {
	if !s.wrote {
		s.wrote = true
	}
	return s.ResponseWriter.Write(b)
}

// metricsMiddleware records request count + latency with a bounded-cardinality
// route-template label (mirrors api/metrics.py MetricsMiddleware).
func (a *App) metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if metricsExempt[r.URL.Path] {
			next.ServeHTTP(w, r)
			return
		}
		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(rec, r)
		route := "unmatched"
		if rctx := chi.RouteContext(r.Context()); rctx != nil {
			if p := rctx.RoutePattern(); p != "" {
				route = p
			}
		}
		elapsed := time.Since(start).Seconds()
		a.metrics.requests.WithLabelValues(r.Method, route, strconv.Itoa(rec.status)).Inc()
		a.metrics.latency.WithLabelValues(r.Method, route).Observe(elapsed)
	})
}

// handleMetrics refreshes the best-effort ARQ queue-depth gauges then serves the
// Prometheus exposition (mirrors api/metrics.py metrics_response).
func (a *App) handleMetrics(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	for _, q := range []struct{ name, key string }{{"worker", queueWorker}, {"bot", queueBot}} {
		n, err := a.rdb.ZCard(ctx, q.key).Result()
		if err != nil {
			n = 0
		}
		a.metrics.queueDepth.WithLabelValues(q.name).Set(float64(n))
	}
	a.metrics.handler.ServeHTTP(w, r)
}
