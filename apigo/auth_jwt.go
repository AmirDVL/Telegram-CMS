package main

import (
	"errors"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Claims mirrors shared/security.py TokenClaims.
type Claims struct {
	Sub       string
	AdminID   int64
	Role      Role
	TokenType string // "access" | "refresh"
	TenantID  *int64
}

func (a *App) signToken(adminID int64, username string, role Role, tenantID *int64, tokenType string, ttl time.Duration) (string, error) {
	now := time.Now()
	claims := jwt.MapClaims{
		"sub":        username,
		"admin_id":   adminID,
		"role":       string(role),
		"token_type": tokenType,
		"iat":        now.Unix(),
		"exp":        now.Add(ttl).Unix(),
	}
	if tenantID != nil {
		claims["tenant_id"] = *tenantID
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return tok.SignedString([]byte(a.cfg.JWTSecret))
}

func (a *App) createAccessToken(adminID int64, username string, role Role, tenantID *int64) (string, error) {
	return a.signToken(adminID, username, role, tenantID, "access",
		time.Duration(a.cfg.AccessTTLMinutes)*time.Minute)
}

func (a *App) createRefreshToken(adminID int64, username string, role Role, tenantID *int64) (string, error) {
	return a.signToken(adminID, username, role, tenantID, "refresh",
		time.Duration(a.cfg.RefreshTTLDays)*24*time.Hour)
}

// decodeToken parses and validates an HS256 token, returning the claims. It
// returns an error for any failure (bad signature, expired, wrong alg) so
// callers can treat it like shared.security.decode_token returning None.
func (a *App) decodeToken(tokenStr string) (*Claims, error) {
	parsed, err := jwt.Parse(tokenStr, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(a.cfg.JWTSecret), nil
	}, jwt.WithValidMethods([]string{"HS256"}))
	if err != nil || !parsed.Valid {
		return nil, errors.New("invalid token")
	}
	mc, ok := parsed.Claims.(jwt.MapClaims)
	if !ok {
		return nil, errors.New("invalid claims")
	}
	c := &Claims{}
	c.Sub, _ = mc["sub"].(string)
	c.TokenType, _ = mc["token_type"].(string)
	if rs, ok := mc["role"].(string); ok {
		c.Role = Role(rs)
	}
	switch v := mc["admin_id"].(type) {
	case float64:
		c.AdminID = int64(v)
	default:
		return nil, errors.New("missing admin_id")
	}
	if tid, ok := mc["tenant_id"]; ok && tid != nil {
		if f, ok := tid.(float64); ok {
			id := int64(f)
			c.TenantID = &id
		}
	}
	return c, nil
}
