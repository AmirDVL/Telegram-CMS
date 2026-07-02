package main

import (
	"context"
	"errors"
	"fmt"
	"net/http"

	"github.com/jackc/pgx/v5"
)

func (a *App) loadTemplate(ctx context.Context, id int64) (*templateRow, error) {
	row := a.db.QueryRow(ctx, `SELECT `+templateCols+` FROM templates WHERE id=$1`, id)
	t, err := scanTemplate(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return t, nil
}

func (a *App) handleListTemplates(w http.ResponseWriter, r *http.Request) {
	q := `SELECT ` + templateCols + ` FROM templates ORDER BY name`
	rows, err := a.db.Query(r.Context(), q)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []TemplateOut{}
	for rows.Next() {
		t, err := scanTemplate(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, t.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *App) handleCreateTemplate(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Name string `json:"name"`
		Body string `json:"body"`
	}
	if err := decodeJSON(r, &in); err != nil || in.Name == "" {
		writeError(w, http.StatusUnprocessableEntity, "name is required")
		return
	}
	row := a.db.QueryRow(r.Context(),
		`INSERT INTO templates(name,body) VALUES($1,$2) RETURNING `+templateCols,
		in.Name, in.Body)
	t, err := scanTemplate(row)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, t.DTO())
}

func (a *App) handleUpdateTemplate(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "templateID")
	if !ok {
		writeError(w, http.StatusNotFound, "template not found")
		return
	}
	t, err := a.loadTemplate(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "template not found")
		return
	}
	var in struct {
		Name *string `json:"name"`
		Body *string `json:"body"`
	}
	if err := decodeJSON(r, &in); err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}
	b := &setBuilder{}
	if in.Name != nil {
		b.add("name", *in.Name)
	}
	if in.Body != nil {
		b.add("body", *in.Body)
	}
	if b.empty() {
		writeJSON(w, http.StatusOK, t.DTO())
		return
	}
	q := `UPDATE templates SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d", len(b.args)+1)
	b.args = append(b.args, id)
	q += ` RETURNING ` + templateCols
	updated, err := scanTemplate(a.db.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}

func (a *App) handleDeleteTemplate(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "templateID")
	if !ok {
		writeError(w, http.StatusNotFound, "template not found")
		return
	}
	t, err := a.loadTemplate(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "template not found")
		return
	}
	if _, err := a.db.Exec(r.Context(), `DELETE FROM templates WHERE id=$1`, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeNoContent(w)
}
