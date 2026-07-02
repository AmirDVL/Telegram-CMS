package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/jackc/pgx/v5"
)

func slugify(value string) (string, bool) {
	var b strings.Builder
	prevDash := false
	for _, c := range strings.ToLower(value) {
		if (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') {
			b.WriteRune(c)
			prevDash = false
		} else if !prevDash {
			b.WriteByte('-')
			prevDash = true
		}
	}
	s := strings.Trim(b.String(), "-")
	if s == "" {
		return "", false
	}
	if len(s) > 64 {
		s = s[:64]
	}
	return s, true
}

func (a *App) loadTag(ctx context.Context, id int64) (*tagRow, error) {
	row := a.db.QueryRow(ctx, `SELECT `+tagCols+` FROM tags WHERE id=$1`, id)
	t, err := scanTag(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return t, nil
}

func (a *App) handleListTags(w http.ResponseWriter, r *http.Request) {
	q := `SELECT ` + tagCols + ` FROM tags ORDER BY label`
	rows, err := a.db.Query(r.Context(), q)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []TagOut{}
	for rows.Next() {
		t, err := scanTag(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, t.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *App) handleCountTags(w http.ResponseWriter, r *http.Request) {
	var n int64
	if err := a.db.QueryRow(r.Context(), `SELECT count(id) FROM tags`).Scan(&n); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, map[string]int64{"total": n})
}

func (a *App) handleCreateTag(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Slug  string  `json:"slug"`
		Label string  `json:"label"`
		Color *string `json:"color"`
	}
	if err := decodeJSON(r, &in); err != nil || in.Slug == "" || in.Label == "" {
		writeError(w, http.StatusUnprocessableEntity, "slug and label are required")
		return
	}
	slug, ok := slugify(in.Slug)
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid slug")
		return
	}
	row := a.db.QueryRow(r.Context(),
		`INSERT INTO tags(slug,label,color) VALUES($1,$2,$3) RETURNING `+tagCols,
		slug, in.Label, in.Color)
	t, err := scanTag(row)
	if err != nil {
		if isUniqueViolation(err) {
			writeError(w, http.StatusConflict, "slug already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, t.DTO())
}

func (a *App) handleUpdateTag(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "tagID")
	if !ok {
		writeError(w, http.StatusNotFound, "tag not found")
		return
	}
	t, err := a.loadTag(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "tag not found")
		return
	}
	var in struct {
		Label *string `json:"label"`
		Color *string `json:"color"`
	}
	if err := decodeJSON(r, &in); err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}
	b := &setBuilder{}
	if in.Label != nil {
		b.add("label", *in.Label)
	}
	if in.Color != nil {
		b.add("color", *in.Color)
	}
	if b.empty() {
		writeJSON(w, http.StatusOK, t.DTO())
		return
	}
	q := `UPDATE tags SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d", len(b.args)+1)
	b.args = append(b.args, id)
	q += ` RETURNING ` + tagCols
	updated, err := scanTag(a.db.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}

func (a *App) handleDeleteTag(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "tagID")
	if !ok {
		writeError(w, http.StatusNotFound, "tag not found")
		return
	}
	t, err := a.loadTag(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "tag not found")
		return
	}
	tx, err := a.db.Begin(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()

	uq := `UPDATE posts SET tag_ids = array_remove(tag_ids, $1) WHERE array_position(tag_ids,$1) IS NOT NULL`
	if _, err := tx.Exec(r.Context(), uq, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if _, err := tx.Exec(r.Context(), `DELETE FROM tags WHERE id=$1`, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeNoContent(w)
}
