package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/redis/go-redis/v9"
)

// App holds the shared dependencies for every handler.
type App struct {
	cfg     *Config
	db      *pgxpool.Pool
	rdb     *redis.Client
	metrics *metricsBundle
}

// runHealthcheck is used as the container healthcheck (distroless has no curl):
// `/api healthcheck` exits 0 if GET /healthz returns 200, else 1.
func runHealthcheck(port string) {
	client := &http.Client{Timeout: 3 * time.Second}
	resp, err := client.Get("http://127.0.0.1:" + port + "/healthz")
	if err != nil || resp.StatusCode != http.StatusOK {
		os.Exit(1)
	}
	_ = resp.Body.Close()
	os.Exit(0)
}

func main() {
	cfg := LoadConfig()

	if len(os.Args) > 1 && os.Args[1] == "healthcheck" {
		runHealthcheck(cfg.Port)
		return
	}

	if err := cfg.RequireAuthSecret(); err != nil {
		log.Fatalf("startup: %v", err)
	}

	ctx := context.Background()

	poolCfg, err := pgxpool.ParseConfig(cfg.PostgresDSN)
	if err != nil {
		log.Fatalf("postgres dsn: %v", err)
	}
	poolCfg.MaxConns = 15 // ~ SQLAlchemy pool_size(10) + max_overflow(5)
	pool, err := pgxpool.NewWithConfig(ctx, poolCfg)
	if err != nil {
		log.Fatalf("postgres: %v", err)
	}
	defer pool.Close()

	ropts, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		log.Fatalf("redis url: %v", err)
	}
	rdb := redis.NewClient(ropts)
	defer func() { _ = rdb.Close() }()

	app := &App{cfg: cfg, db: pool, rdb: rdb, metrics: newMetrics()}

	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           app.router(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("api listening on :%s", cfg.Port)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
	<-stop

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = srv.Shutdown(shutdownCtx)
}
