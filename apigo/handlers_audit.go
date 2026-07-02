package main

import (
	"fmt"
	"net/http"
	"strconv"
	"strings"
)

var eventActions = map[string]bool{
	"ingested": true, "edited": true, "approved": true, "rejected": true,
	"scheduled": true, "published": true, "publish_failed": true, "duplicate": true,
	"media_omitted": true, "draft_posted": true, "ai_transformed": true, "ai_failed": true,
}

func (a *App) handleListEvents(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()

	var where []string
	var wargs []any

	if v := q.Get("post_id"); v != "" {
		pid, err := strconv.ParseInt(v, 10, 64)
		if err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid post_id")
			return
		}
		wargs = append(wargs, pid)
		where = append(where, fmt.Sprintf("post_id=$%d", len(wargs)))
	}
	actions := q["action"]
	for _, s := range actions {
		if !eventActions[s] {
			writeError(w, http.StatusUnprocessableEntity, "invalid action")
			return
		}
	}
	if len(actions) > 0 {
		wargs = append(wargs, actions)
		where = append(where, fmt.Sprintf("action::text = ANY($%d)", len(wargs)))
	}
	limit := 100
	if v := q.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n > 500 {
			writeError(w, http.StatusUnprocessableEntity, "limit must be <= 500")
			return
		}
		limit = n
	}
	offset := 0
	if v := q.Get("offset"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			offset = n
		}
	}

	clause := ""
	if len(where) > 0 {
		clause = " WHERE " + strings.Join(where, " AND ")
	}

	var total int64
	if err := a.db.QueryRow(r.Context(), `SELECT count(id) FROM post_events`+clause, wargs...).Scan(&total); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	iargs := append([]any{}, wargs...)
	iargs = append(iargs, limit, offset)
	q2 := `SELECT ` + postEventCols + ` FROM post_events` + clause +
		fmt.Sprintf(" ORDER BY created_at DESC LIMIT $%d OFFSET $%d", len(wargs)+1, len(wargs)+2)
	rows, err := a.db.Query(r.Context(), q2, iargs...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	items := []PostEventOut{}
	for rows.Next() {
		e, err := scanPostEvent(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		items = append(items, e.DTO())
	}
	writeJSON(w, http.StatusOK, Paginated{Items: items, Total: total, Limit: limit, Offset: offset})
}

func (a *App) handleListPostEvents(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "postID")
	if !ok {
		writeJSON(w, http.StatusOK, []PostEventOut{})
		return
	}
	rows, err := a.db.Query(r.Context(),
		`SELECT `+postEventCols+` FROM post_events WHERE post_id=$1 ORDER BY created_at ASC`, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []PostEventOut{}
	for rows.Next() {
		e, err := scanPostEvent(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, e.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}
