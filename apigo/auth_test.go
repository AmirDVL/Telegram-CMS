package main

import "testing"

func testApp() *App {
	return &App{cfg: &Config{
		JWTSecret:        "test-secret-0123456789-not-a-placeholder",
		JWTAlgo:          "HS256",
		AccessTTLMinutes: 30,
		RefreshTTLDays:   14,
	}}
}

func TestJWTAccessRoundTrip(t *testing.T) {
	a := testApp()
	tok, err := a.createAccessToken(42, "alice", RoleAdmin)
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	claims, err := a.decodeToken(tok)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if claims.AdminID != 42 {
		t.Errorf("admin_id = %d, want 42", claims.AdminID)
	}
	if claims.Sub != "alice" {
		t.Errorf("sub = %q, want alice", claims.Sub)
	}
	if claims.Role != RoleAdmin {
		t.Errorf("role = %q, want admin", claims.Role)
	}
	if claims.TokenType != "access" {
		t.Errorf("token_type = %q, want access", claims.TokenType)
	}
}

func TestJWTRefreshType(t *testing.T) {
	a := testApp()
	tok, err := a.createRefreshToken(1, "bob", RoleEditor)
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	claims, err := a.decodeToken(tok)
	if err != nil {
		t.Fatalf("decode: %v", err)
	}
	if claims.TokenType != "refresh" {
		t.Errorf("token_type = %q, want refresh", claims.TokenType)
	}
}

func TestJWTRejectsWrongSecret(t *testing.T) {
	a := testApp()
	tok, _ := a.createAccessToken(1, "x", RoleEditor)
	other := &App{cfg: &Config{JWTSecret: "a-totally-different-secret-value", JWTAlgo: "HS256"}}
	if _, err := other.decodeToken(tok); err == nil {
		t.Error("expected decode to fail with a different secret")
	}
}

func TestArgon2RoundTrip(t *testing.T) {
	hash, err := hashPassword("correct horse battery staple")
	if err != nil {
		t.Fatalf("hash: %v", err)
	}
	if !verifyPassword("correct horse battery staple", hash) {
		t.Error("verify should accept the correct password")
	}
	if verifyPassword("wrong password", hash) {
		t.Error("verify should reject a wrong password")
	}
}

func TestArgon2RejectsMalformed(t *testing.T) {
	for _, bad := range []string{"", "not-a-hash", "$argon2id$v=19$bad", "$bcrypt$x$y$z$w$v"} {
		if verifyPassword("x", bad) {
			t.Errorf("verify should reject malformed hash %q", bad)
		}
	}
}

func TestRoleAtLeast(t *testing.T) {
	if !roleAtLeast(RoleSuperAdmin, RoleEditor) {
		t.Error("super_admin should satisfy editor")
	}
	if roleAtLeast(RoleEditor, RoleAdmin) {
		t.Error("editor should not satisfy admin")
	}
	if !roleAtLeast(RoleAdmin, RoleAdmin) {
		t.Error("admin should satisfy admin")
	}
}
