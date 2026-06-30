package main

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
)

// writeJSON serialises v compactly (no trailing newline) to match Starlette's
// JSONResponse, which uses compact separators.
func writeJSON(w http.ResponseWriter, status int, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusInternalServerError)
		_, _ = w.Write([]byte(`{"detail":"internal error"}`))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

// writeError mirrors FastAPI's {"detail": "..."} error body.
func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeNoContent(w http.ResponseWriter) {
	w.WriteHeader(http.StatusNoContent)
}

// decodeJSON reads a JSON request body into dst. An empty body is treated as an
// empty object so optional-body endpoints (e.g. /auth/refresh, /queue approve)
// behave like FastAPI's default_factory models.
func decodeJSON(r *http.Request, dst any) error {
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil {
		if errors.Is(err, io.EOF) {
			return nil
		}
		return err
	}
	return nil
}
