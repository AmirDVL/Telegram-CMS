package main

import (
	"encoding/json"
	"testing"
)

// TestBuildPublishJobBody pins the ARQ-compatible JSON job shape the Python bot
// worker consumes: {t:null, f:"publish", a:[post_id], k:{}, et:<ms>}.
func TestBuildPublishJobBody(t *testing.T) {
	body, err := buildPublishJobBody(123, 1751299200000)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	var m map[string]any
	if err := json.Unmarshal(body, &m); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if _, ok := m["t"]; !ok || m["t"] != nil {
		t.Errorf("t = %v, want null", m["t"])
	}
	if m["f"] != "publish" {
		t.Errorf("f = %v, want publish", m["f"])
	}
	a, ok := m["a"].([]any)
	if !ok || len(a) != 1 || a[0].(float64) != 123 {
		t.Errorf("a = %v, want [123]", m["a"])
	}
	k, ok := m["k"].(map[string]any)
	if !ok || len(k) != 0 {
		t.Errorf("k = %v, want {}", m["k"])
	}
	if et, ok := m["et"].(float64); !ok || int64(et) != 1751299200000 {
		t.Errorf("et = %v, want 1751299200000", m["et"])
	}
}

func TestSlugify(t *testing.T) {
	cases := map[string]string{
		"Breaking News":    "breaking-news",
		"  Hello!! World ": "hello-world",
		"Tech/Science":     "tech-science",
		"UPPER_case":       "upper-case",
	}
	for in, want := range cases {
		got, ok := slugify(in)
		if !ok || got != want {
			t.Errorf("slugify(%q) = %q,%v; want %q", in, got, ok, want)
		}
	}
	if _, ok := slugify("!!!"); ok {
		t.Error("slugify of punctuation-only should fail")
	}
}

func TestFormatInt64List(t *testing.T) {
	if got := formatInt64List([]int64{3, 5}); got != "[3, 5]" {
		t.Errorf("formatInt64List = %q, want [3, 5]", got)
	}
	if got := formatInt64List(nil); got != "[]" {
		t.Errorf("formatInt64List(nil) = %q, want []", got)
	}
}

func TestNormalizeDSN(t *testing.T) {
	got := normalizeDSN("postgresql+asyncpg://u:p@h:5432/db")
	if got != "postgres://u:p@h:5432/db" {
		t.Errorf("normalizeDSN = %q", got)
	}
}
