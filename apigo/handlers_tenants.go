package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"regexp"

	"github.com/jackc/pgx/v5"
)

var tenantSlugRe = regexp.MustCompile(`^[a-z0-9_-]+$`)

func (a *App) checkMT(w http.ResponseWriter) bool {
	if !a.cfg.MultiTenancy {
		writeError(w, http.StatusNotFound, "multi-tenancy is not enabled")
		return false
	}
	return true
}

func (a *App) loadTenant(ctx context.Context, id int64) (*tenantRow, error) {
	row := a.db.QueryRow(ctx, `SELECT `+tenantCols+` FROM tenants WHERE id=$1`, id)
	t, err := scanTenant(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return t, nil
}

func (a *App) handleListTenants(w http.ResponseWriter, r *http.Request) {
	if !a.checkMT(w) {
		return
	}
	rows, err := a.db.Query(r.Context(), `SELECT `+tenantCols+` FROM tenants ORDER BY name`)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []TenantOut{}
	for rows.Next() {
		t, err := scanTenant(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, t.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *App) handleGetTenant(w http.ResponseWriter, r *http.Request) {
	if !a.checkMT(w) {
		return
	}
	id, ok := urlInt64(r, "tenantID")
	if !ok {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	t, err := a.loadTenant(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	writeJSON(w, http.StatusOK, t.DTO())
}

func (a *App) handleCreateTenant(w http.ResponseWriter, r *http.Request) {
	if !a.checkMT(w) {
		return
	}
	var in struct {
		Slug                  string   `json:"slug"`
		Name                  string   `json:"name"`
		BotToken              *string  `json:"bot_token"`
		DestinationChannelID  *int64   `json:"destination_channel_id"`
		EditorGroupID         *int64   `json:"editor_group_id"`
		AIEnabled             *bool    `json:"ai_enabled"`
		AIMode                *string  `json:"ai_mode"`
		AITargetLanguage      *string  `json:"ai_target_language"`
		AITonePrompt          *string  `json:"ai_tone_prompt"`
		AICustomSystemPrompt  *string  `json:"ai_custom_system_prompt"`
		WatermarkEnabled      *bool    `json:"watermark_enabled"`
		WatermarkText         *string  `json:"watermark_text"`
		StripSourceTags       *bool    `json:"strip_source_tags"`
		AIModel               *string  `json:"ai_model"`
		AIMaxTokens           *int64   `json:"ai_max_tokens"`
		AITimeoutSeconds      *int64   `json:"ai_timeout_seconds"`
		DedupeLookbackDays    *int64   `json:"dedupe_lookback_days"`
		PublishSpacingSeconds *float64 `json:"publish_spacing_seconds"`
		MediaMaxSizeBytes     *int64   `json:"media_max_size_bytes"`
	}
	if err := decodeJSON(r, &in); err != nil || in.Name == "" || len(in.Slug) < 2 || !tenantSlugRe.MatchString(in.Slug) {
		writeError(w, http.StatusUnprocessableEntity, "valid slug and name are required")
		return
	}
	aiMode := "off"
	if in.AIMode != nil && *in.AIMode != "" {
		aiMode = *in.AIMode
	}
	row := a.db.QueryRow(r.Context(),
		`INSERT INTO tenants(
			slug, name, bot_token, destination_channel_id, editor_group_id,
			ai_enabled, ai_mode, ai_target_language, ai_tone_prompt, ai_custom_system_prompt,
			watermark_enabled, watermark_text, strip_source_tags,
			ai_model, ai_max_tokens, ai_timeout_seconds, dedupe_lookback_days,
			publish_spacing_seconds, media_max_size_bytes)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
		RETURNING `+tenantCols,
		in.Slug, in.Name, in.BotToken, in.DestinationChannelID, in.EditorGroupID,
		boolOr(in.AIEnabled, false), aiMode, in.AITargetLanguage, in.AITonePrompt, in.AICustomSystemPrompt,
		boolOr(in.WatermarkEnabled, false), in.WatermarkText, boolOr(in.StripSourceTags, false),
		in.AIModel, in.AIMaxTokens, in.AITimeoutSeconds, in.DedupeLookbackDays,
		in.PublishSpacingSeconds, in.MediaMaxSizeBytes)
	t, err := scanTenant(row)
	if err != nil {
		if isUniqueViolation(err) {
			writeError(w, http.StatusConflict, "tenant slug already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, t.DTO())
}

func (a *App) handleUpdateTenant(w http.ResponseWriter, r *http.Request) {
	if !a.checkMT(w) {
		return
	}
	id, ok := urlInt64(r, "tenantID")
	if !ok {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	t, err := a.loadTenant(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	body, err := decodePatchBody(r)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}

	b := &setBuilder{}
	_ = b.addStr(body, "name", "name")
	_ = b.addStr(body, "bot_token", "bot_token")
	_ = b.addInt(body, "destination_channel_id", "destination_channel_id")
	_ = b.addInt(body, "editor_group_id", "editor_group_id")
	_ = b.addBool(body, "ai_enabled", "ai_enabled")
	_ = b.addStr(body, "ai_mode", "ai_mode")
	_ = b.addStr(body, "ai_target_language", "ai_target_language")
	_ = b.addStr(body, "ai_tone_prompt", "ai_tone_prompt")
	_ = b.addStr(body, "ai_custom_system_prompt", "ai_custom_system_prompt")
	_ = b.addBool(body, "watermark_enabled", "watermark_enabled")
	_ = b.addStr(body, "watermark_text", "watermark_text")
	_ = b.addBool(body, "strip_source_tags", "strip_source_tags")
	_ = b.addStr(body, "ai_model", "ai_model")
	_ = b.addInt(body, "ai_max_tokens", "ai_max_tokens")
	_ = b.addInt(body, "ai_timeout_seconds", "ai_timeout_seconds")
	_ = b.addInt(body, "dedupe_lookback_days", "dedupe_lookback_days")
	_ = b.addFloat(body, "publish_spacing_seconds", "publish_spacing_seconds")
	_ = b.addInt(body, "media_max_size_bytes", "media_max_size_bytes")

	if raw, ok := presentNotNull(body, "disabled"); ok {
		var disabled bool
		if err := json.Unmarshal(raw, &disabled); err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid disabled")
			return
		}
		if disabled {
			b.addRaw("disabled_at=now()")
		} else {
			b.addRaw("disabled_at=NULL")
		}
	}

	if b.empty() {
		writeJSON(w, http.StatusOK, t.DTO())
		return
	}
	q := `UPDATE tenants SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d RETURNING ", len(b.args)+1) + tenantCols
	b.args = append(b.args, id)
	updated, err := scanTenant(a.db.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}

func (a *App) handleDeleteTenant(w http.ResponseWriter, r *http.Request) {
	if !a.checkMT(w) {
		return
	}
	id, ok := urlInt64(r, "tenantID")
	if !ok {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	t, err := a.loadTenant(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if t == nil {
		writeError(w, http.StatusNotFound, "tenant not found")
		return
	}
	// Soft-delete (disable) to preserve referential integrity.
	if _, err := a.db.Exec(r.Context(), `UPDATE tenants SET disabled_at=now() WHERE id=$1`, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeNoContent(w)
}
