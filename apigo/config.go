package main

import (
	"fmt"
	"os"
	"strconv"
	"strings"
)

// Config mirrors the subset of shared/config.py Settings that the API needs.
// Values come from the same environment variables docker-compose injects.
type Config struct {
	PostgresDSN      string
	RedisURL         string
	JWTSecret        string
	JWTAlgo          string
	AccessTTLMinutes int
	RefreshTTLDays   int
	CORSOrigins      string
	AppDomain        string
	MultiTenancy     bool

	AIEnabled        bool
	AIProviderURL    string
	AIAPIKey         string
	AIModel          string
	AIMaxTokens      int
	AITimeoutSeconds int

	MediaMaxSizeDefault int64

	Port string
}

func getenvInt64(key string, def int64) int64 {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64); err == nil {
			return n
		}
	}
	return def
}

func getenv(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getenvInt(key string, def int) int {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil {
			return n
		}
	}
	return def
}

func getenvBool(key string, def bool) bool {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		switch strings.ToLower(strings.TrimSpace(v)) {
		case "1", "true", "yes", "on":
			return true
		case "0", "false", "no", "off":
			return false
		}
	}
	return def
}

// LoadConfig reads configuration from the environment, applying the same
// defaults as shared/config.py.
func LoadConfig() *Config {
	return &Config{
		PostgresDSN:      normalizeDSN(getenv("POSTGRES_DSN", "postgresql+asyncpg://cms:cms@postgres:5432/cms")),
		RedisURL:         getenv("REDIS_URL", "redis://redis:6379/0"),
		JWTSecret:        getenv("JWT_SECRET", ""),
		JWTAlgo:          getenv("JWT_ALGO", "HS256"),
		AccessTTLMinutes: getenvInt("ACCESS_TOKEN_TTL_MINUTES", 30),
		RefreshTTLDays:   getenvInt("REFRESH_TOKEN_TTL_DAYS", 14),
		CORSOrigins:      getenv("CORS_ORIGINS", "*"),
		AppDomain:        getenv("APP_DOMAIN", "localhost"),
		MultiTenancy:     getenvBool("MULTI_TENANCY_ENABLED", false),
		AIEnabled:        getenvBool("AI_ENABLED", false),
		AIProviderURL:    getenv("AI_PROVIDER_URL", "https://api.openai.com/v1"),
		AIAPIKey:         getenv("AI_API_KEY", ""),
		AIModel:          getenv("AI_MODEL", "gpt-4o-mini"),
		AIMaxTokens:      getenvInt("AI_MAX_TOKENS", 2048),
		AITimeoutSeconds: getenvInt("AI_TIMEOUT_SECONDS", 30),

		MediaMaxSizeDefault: getenvInt64("MEDIA_MAX_SIZE_DEFAULT", 2147483648),

		Port: getenv("API_PORT", "8000"),
	}
}

// normalizeDSN converts a SQLAlchemy DSN (postgresql+asyncpg://...) into the
// libpq/pgx form (postgres://...).
func normalizeDSN(dsn string) string {
	dsn = strings.Replace(dsn, "postgresql+asyncpg://", "postgres://", 1)
	dsn = strings.Replace(dsn, "postgresql://", "postgres://", 1)
	return dsn
}

// CORSList mirrors Settings.cors_origin_list.
func (c *Config) CORSList() []string {
	if strings.TrimSpace(c.CORSOrigins) == "*" {
		return []string{"*"}
	}
	parts := strings.Split(c.CORSOrigins, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// IsProduction mirrors the Secure-cookie decision in api/auth.py.
func (c *Config) IsProduction() bool {
	return c.AppDomain != "localhost" && c.AppDomain != ""
}

// AuthSecretValid mirrors Settings.auth_secret_valid.
func (c *Config) AuthSecretValid() bool {
	return c.JWTSecret != "" && !strings.HasPrefix(c.JWTSecret, "change-this")
}

// RequireAuthSecret mirrors Settings.require_auth_secret (fail-fast on startup).
func (c *Config) RequireAuthSecret() error {
	if !c.AuthSecretValid() {
		return fmt.Errorf("JWT_SECRET must be set to a strong random string (got empty/placeholder)")
	}
	return nil
}
