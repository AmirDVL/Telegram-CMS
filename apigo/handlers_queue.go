package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

var postStates = map[string]bool{
	"pending": true, "approved": true, "scheduled": true, "published": true,
	"rejected": true, "publishing": true, "publish_failed": true,
}

func mustJSON(v any) []byte {
	b, _ := json.Marshal(v)
	return b
}

func (a *App) loadPost(ctx context.Context, id int64) (*postRow, error) {
	row := a.db.QueryRow(ctx, `SELECT `+postCols+` FROM posts WHERE id=$1`, id)
	p, err := scanPost(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return p, nil
}

func (a *App) handleListQueue(w http.ResponseWriter, r *http.Request) {
	tid := tenantID(r)
	q := r.URL.Query()
	states := q["state"]
	for _, s := range states {
		if !postStates[s] {
			writeError(w, http.StatusUnprocessableEntity, "invalid state")
			return
		}
	}
	limit := 50
	if v := q.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n > 200 {
			writeError(w, http.StatusUnprocessableEntity, "limit must be <= 200")
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

	var where []string
	var wargs []any
	if len(states) > 0 {
		wargs = append(wargs, states)
		where = append(where, fmt.Sprintf("state::text = ANY($%d)", len(wargs)))
	}
	if a.scoped(tid) {
		wargs = append(wargs, *tid)
		where = append(where, fmt.Sprintf("tenant_id=$%d", len(wargs)))
	}
	clause := ""
	if len(where) > 0 {
		clause = " WHERE " + strings.Join(where, " AND ")
	}

	var total int64
	if err := a.db.QueryRow(r.Context(), `SELECT count(id) FROM posts`+clause, wargs...).Scan(&total); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}

	iargs := append([]any{}, wargs...)
	iargs = append(iargs, limit, offset)
	q2 := `SELECT ` + postCols + ` FROM posts` + clause +
		fmt.Sprintf(" ORDER BY received_at DESC LIMIT $%d OFFSET $%d", len(wargs)+1, len(wargs)+2)
	rows, err := a.db.Query(r.Context(), q2, iargs...)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	items := []PostOut{}
	for rows.Next() {
		p, err := scanPost(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		items = append(items, p.DTO())
	}
	writeJSON(w, http.StatusOK, Paginated{Items: items, Total: total, Limit: limit, Offset: offset})
}

func (a *App) handleGetPost(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "postID")
	if !ok {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	tid := tenantID(r)
	p, err := a.loadPost(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if p == nil || !a.tenantOwned(tid, p.TenantID) {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	writeJSON(w, http.StatusOK, p.DTO())
}

func (a *App) handleEditTags(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "postID")
	if !ok {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	tid := tenantID(r)
	actor := adminFromCtx(r)
	p, err := a.loadPost(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if p == nil || !a.tenantOwned(tid, p.TenantID) {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	var in struct {
		TagIDs *[]int64 `json:"tag_ids"`
	}
	if err := decodeJSON(r, &in); err != nil || in.TagIDs == nil {
		writeError(w, http.StatusUnprocessableEntity, "tag_ids is required")
		return
	}
	tags := *in.TagIDs
	updated, err := a.applyPostUpdate(r.Context(),
		`UPDATE posts SET tag_ids=$1, updated_at=now() WHERE id=$2 RETURNING `+postCols,
		[]any{tags, id},
		id, actor.ID, "edited", mustJSON(map[string]any{"tag_ids": tags}))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}

// applyPostUpdate runs the UPDATE + a post_events insert in one transaction and
// returns the updated post row.
func (a *App) applyPostUpdate(ctx context.Context, updateSQL string, updateArgs []any, postID, actorID int64, action string, payload []byte) (*postRow, error) {
	tx, err := a.db.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback(ctx) }()

	updated, err := scanPost(tx.QueryRow(ctx, updateSQL, updateArgs...))
	if err != nil {
		return nil, err
	}
	if _, err := tx.Exec(ctx,
		`INSERT INTO post_events(post_id, actor_admin_id, action, payload) VALUES($1,$2,$3,$4)`,
		postID, actorID, action, payload); err != nil {
		return nil, err
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, err
	}
	return updated, nil
}

func (a *App) decide(w http.ResponseWriter, r *http.Request, action string, tagIDs *[]int64, scheduledFor *time.Time) {
	id, ok := urlInt64(r, "postID")
	if !ok {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	tid := tenantID(r)
	actor := adminFromCtx(r)
	p, err := a.loadPost(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if p == nil || !a.tenantOwned(tid, p.TenantID) {
		writeError(w, http.StatusNotFound, "post not found")
		return
	}
	finalTags := p.TagIDs
	if tagIDs != nil {
		finalTags = *tagIDs
	}
	if finalTags == nil {
		finalTags = []int64{}
	}

	switch action {
	case "approve":
		updated, err := a.applyPostUpdate(r.Context(),
			`UPDATE posts SET state='approved', scheduled_for=NULL, tag_ids=$1, updated_at=now() WHERE id=$2 RETURNING `+postCols,
			[]any{finalTags, id},
			id, actor.ID, "approved", mustJSON(map[string]any{"tag_ids": finalTags}))
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		if err := a.enqueuePublish(r.Context(), id, 0); err != nil {
			writeError(w, http.StatusInternalServerError, "enqueue error")
			return
		}
		writeJSON(w, http.StatusOK, updated.DTO())

	case "schedule":
		if scheduledFor == nil {
			writeError(w, http.StatusBadRequest, "scheduled_for is required")
			return
		}
		now := time.Now().UTC()
		if !scheduledFor.After(now) {
			writeError(w, http.StatusBadRequest, "scheduled_for must be in the future")
			return
		}
		payload := mustJSON(map[string]any{
			"tag_ids":       finalTags,
			"scheduled_for": scheduledFor.Format(time.RFC3339Nano),
		})
		updated, err := a.applyPostUpdate(r.Context(),
			`UPDATE posts SET state='scheduled', scheduled_for=$1, tag_ids=$2, updated_at=now() WHERE id=$3 RETURNING `+postCols,
			[]any{*scheduledFor, finalTags, id},
			id, actor.ID, "scheduled", payload)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		if err := a.enqueuePublish(r.Context(), id, scheduledFor.Sub(now)); err != nil {
			writeError(w, http.StatusInternalServerError, "enqueue error")
			return
		}
		writeJSON(w, http.StatusOK, updated.DTO())

	case "reject":
		updated, err := a.applyPostUpdate(r.Context(),
			`UPDATE posts SET state='rejected', tag_ids=$1, updated_at=now() WHERE id=$2 RETURNING `+postCols,
			[]any{finalTags, id},
			id, actor.ID, "rejected", mustJSON(map[string]any{"tag_ids": finalTags}))
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		writeJSON(w, http.StatusOK, updated.DTO())

	default:
		writeError(w, http.StatusBadRequest, "action must be approve|schedule|reject")
	}
}

func (a *App) handleDecision(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Action       string     `json:"action"`
		TagIDs       *[]int64   `json:"tag_ids"`
		ScheduledFor *time.Time `json:"scheduled_for"`
	}
	if err := decodeJSON(r, &in); err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}
	if in.Action != "approve" && in.Action != "schedule" && in.Action != "reject" {
		writeError(w, http.StatusBadRequest, "action must be approve|schedule|reject")
		return
	}
	a.decide(w, r, in.Action, in.TagIDs, in.ScheduledFor)
}

func (a *App) handleApprove(w http.ResponseWriter, r *http.Request) {
	var in struct {
		TagIDs *[]int64 `json:"tag_ids"`
	}
	_ = decodeJSON(r, &in) // body is optional
	a.decide(w, r, "approve", in.TagIDs, nil)
}

func (a *App) handleSchedule(w http.ResponseWriter, r *http.Request) {
	var in struct {
		ScheduledFor *time.Time `json:"scheduled_for"`
	}
	if err := decodeJSON(r, &in); err != nil || in.ScheduledFor == nil {
		writeError(w, http.StatusUnprocessableEntity, "scheduled_for is required")
		return
	}
	a.decide(w, r, "schedule", nil, in.ScheduledFor)
}

func (a *App) handleReject(w http.ResponseWriter, r *http.Request) {
	a.decide(w, r, "reject", nil, nil)
}
