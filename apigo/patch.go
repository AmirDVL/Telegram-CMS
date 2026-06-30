package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
)

// setBuilder accumulates "col=$n" assignments for a presence-aware UPDATE,
// mirroring pydantic's model_dump(exclude_unset=True) + per-field setattr.
type setBuilder struct {
	sets []string
	args []any
}

func (b *setBuilder) add(col string, val any) {
	b.args = append(b.args, val)
	b.sets = append(b.sets, fmt.Sprintf("%s=$%d", col, len(b.args)))
}

// addRaw appends a literal assignment (e.g. "disabled_at=now()") with no arg.
func (b *setBuilder) addRaw(expr string) { b.sets = append(b.sets, expr) }

func (b *setBuilder) empty() bool    { return len(b.sets) == 0 }
func (b *setBuilder) clause() string { return strings.Join(b.sets, ", ") }

// presentNotNull reports whether key is present and not JSON null.
func presentNotNull(body map[string]json.RawMessage, key string) (json.RawMessage, bool) {
	raw, ok := body[key]
	if !ok || string(raw) == "null" {
		return nil, false
	}
	return raw, true
}

// decodePatchBody reads a PATCH body into a presence map so we can tell which
// fields the client actually sent (matching FastAPI's exclude_unset semantics).
func decodePatchBody(r *http.Request) (map[string]json.RawMessage, error) {
	body := map[string]json.RawMessage{}
	if err := decodeJSON(r, &body); err != nil {
		return nil, err
	}
	return body, nil
}

// addStr applies a nullable string field if present (null → SQL NULL).
func (b *setBuilder) addStr(body map[string]json.RawMessage, key, col string) error {
	if raw, ok := body[key]; ok {
		var v *string
		if err := json.Unmarshal(raw, &v); err != nil {
			return err
		}
		b.add(col, v)
	}
	return nil
}

func (b *setBuilder) addBool(body map[string]json.RawMessage, key, col string) error {
	if raw, ok := body[key]; ok {
		var v *bool
		if err := json.Unmarshal(raw, &v); err != nil {
			return err
		}
		b.add(col, v)
	}
	return nil
}

func (b *setBuilder) addInt(body map[string]json.RawMessage, key, col string) error {
	if raw, ok := body[key]; ok {
		var v *int64
		if err := json.Unmarshal(raw, &v); err != nil {
			return err
		}
		b.add(col, v)
	}
	return nil
}

func (b *setBuilder) addFloat(body map[string]json.RawMessage, key, col string) error {
	if raw, ok := body[key]; ok {
		var v *float64
		if err := json.Unmarshal(raw, &v); err != nil {
			return err
		}
		b.add(col, v)
	}
	return nil
}
