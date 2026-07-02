package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
)

func formatInt64List(xs []int64) string {
	parts := make([]string, len(xs))
	for i, x := range xs {
		parts[i] = strconv.FormatInt(x, 10)
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

func derefStr(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func (a *App) loadChannel(ctx context.Context, id int64) (*channelRow, error) {
	row := a.db.QueryRow(ctx, `SELECT `+channelCols+` FROM source_channels WHERE id=$1`, id)
	c, err := scanChannel(row)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return c, nil
}

// setDefaultTagLinks mirrors source_channels._set_default_tag_links: replace the
// join rows, validating that all referenced tags exist. Returns the sorted set
// of missing tag ids (caller responds 400) when any are unknown.
func (a *App) setDefaultTagLinks(ctx context.Context, tx pgx.Tx, channelID int64, tagIDs []int64) (missing []int64, err error) {
	if _, err = tx.Exec(ctx, `DELETE FROM source_channel_tags WHERE source_channel_id=$1`, channelID); err != nil {
		return nil, err
	}
	if len(tagIDs) == 0 {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `SELECT id FROM tags WHERE id = ANY($1)`, tagIDs)
	if err != nil {
		return nil, err
	}
	existing := map[int64]bool{}
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		existing[id] = true
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}

	seen := map[int64]bool{}
	for _, id := range tagIDs {
		if !existing[id] && !seen[id] {
			seen[id] = true
			missing = append(missing, id)
		}
	}
	if len(missing) > 0 {
		sort.Slice(missing, func(i, j int) bool { return missing[i] < missing[j] })
		return missing, nil
	}
	for _, id := range tagIDs {
		if _, err := tx.Exec(ctx,
			`INSERT INTO source_channel_tags(source_channel_id, tag_id) VALUES($1,$2)`, channelID, id); err != nil {
			return nil, err
		}
	}
	return nil, nil
}

func (a *App) handleListChannels(w http.ResponseWriter, r *http.Request) {
	q := `SELECT ` + channelCols + ` FROM source_channels ORDER BY title`
	rows, err := a.db.Query(r.Context(), q)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer rows.Close()
	out := []SourceChannelOut{}
	for rows.Next() {
		c, err := scanChannel(rows)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		out = append(out, c.DTO())
	}
	writeJSON(w, http.StatusOK, out)
}

func (a *App) handleCreateChannel(w http.ResponseWriter, r *http.Request) {
	var in struct {
		TelegramChannelID       *int64  `json:"telegram_channel_id"`
		Title                   string  `json:"title"`
		Username                *string `json:"username"`
		IngestionEnabled        *bool   `json:"ingestion_enabled"`
		Policy                  *string `json:"policy"`
		DefaultTagIDs           []int64 `json:"default_tag_ids"`
		NormalizationTemplateID *int64  `json:"normalization_template_id"`
		MaxMediaSizeBytes       *int64  `json:"max_media_size_bytes"`
		SourceLabel             *string `json:"source_label"`
		AIEnabled               *bool   `json:"ai_enabled"`
		AIMode                  *string `json:"ai_mode"`
		AITargetLanguage        *string `json:"ai_target_language"`
		AITonePrompt            *string `json:"ai_tone_prompt"`
		AICustomSystemPrompt    *string `json:"ai_custom_system_prompt"`
		WatermarkEnabled        *bool   `json:"watermark_enabled"`
		WatermarkText           *string `json:"watermark_text"`
		StripSourceTags         *bool   `json:"strip_source_tags"`
	}
	if err := decodeJSON(r, &in); err != nil || in.TelegramChannelID == nil || in.Title == "" {
		writeError(w, http.StatusUnprocessableEntity, "telegram_channel_id and title are required")
		return
	}
	ingestion := true
	if in.IngestionEnabled != nil {
		ingestion = *in.IngestionEnabled
	}
	policy := "queue"
	if in.Policy != nil && *in.Policy != "" {
		policy = *in.Policy
	}
	maxMedia := a.cfg.MediaMaxSizeDefault
	if in.MaxMediaSizeBytes != nil && *in.MaxMediaSizeBytes != 0 {
		maxMedia = *in.MaxMediaSizeBytes
	}
	aiEnabled := boolOr(in.AIEnabled, false)
	aiMode := "off"
	if in.AIMode != nil && *in.AIMode != "" {
		aiMode = *in.AIMode
	}
	wmEnabled := boolOr(in.WatermarkEnabled, false)
	strip := boolOr(in.StripSourceTags, false)
	if in.DefaultTagIDs == nil {
		in.DefaultTagIDs = []int64{}
	}

	tx, err := a.db.Begin(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()

	row := tx.QueryRow(r.Context(),
		`INSERT INTO source_channels(
			telegram_channel_id, title, username, ingestion_enabled, policy, default_tag_ids,
			normalization_template_id, max_media_size_bytes, source_label,
			ai_enabled, ai_mode, ai_target_language, ai_tone_prompt, ai_custom_system_prompt,
			watermark_enabled, watermark_text, strip_source_tags)
		VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
		RETURNING `+channelCols,
		*in.TelegramChannelID, in.Title, in.Username, ingestion, policy, in.DefaultTagIDs,
		in.NormalizationTemplateID, maxMedia, in.SourceLabel,
		aiEnabled, aiMode, in.AITargetLanguage, in.AITonePrompt, in.AICustomSystemPrompt,
		wmEnabled, in.WatermarkText, strip)
	c, err := scanChannel(row)
	if err != nil {
		if isUniqueViolation(err) {
			writeError(w, http.StatusConflict, "channel already exists")
			return
		}
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	missing, err := a.setDefaultTagLinks(r.Context(), tx, c.ID, in.DefaultTagIDs)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if missing != nil {
		writeError(w, http.StatusBadRequest, "unknown tag ids: "+formatInt64List(missing))
		return
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusCreated, c.DTO())
}

func boolOr(p *bool, def bool) bool {
	if p != nil {
		return *p
	}
	return def
}

func (a *App) handleUpdateChannel(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "channelID")
	if !ok {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	c, err := a.loadChannel(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	body, err := decodePatchBody(r)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}

	b := &setBuilder{}
	_ = b.addStr(body, "title", "title")
	_ = b.addStr(body, "username", "username")
	_ = b.addBool(body, "ingestion_enabled", "ingestion_enabled")
	_ = b.addStr(body, "policy", "policy")
	_ = b.addInt(body, "normalization_template_id", "normalization_template_id")
	_ = b.addInt(body, "max_media_size_bytes", "max_media_size_bytes")
	_ = b.addStr(body, "source_label", "source_label")
	_ = b.addBool(body, "ai_enabled", "ai_enabled")
	_ = b.addStr(body, "ai_mode", "ai_mode")
	_ = b.addStr(body, "ai_target_language", "ai_target_language")
	_ = b.addStr(body, "ai_tone_prompt", "ai_tone_prompt")
	_ = b.addStr(body, "ai_custom_system_prompt", "ai_custom_system_prompt")
	_ = b.addBool(body, "watermark_enabled", "watermark_enabled")
	_ = b.addStr(body, "watermark_text", "watermark_text")
	_ = b.addBool(body, "strip_source_tags", "strip_source_tags")

	tagChange := false
	var tagIDs []int64
	if raw, ok := body["default_tag_ids"]; ok {
		if err := json.Unmarshal(raw, &tagIDs); err != nil {
			writeError(w, http.StatusUnprocessableEntity, "invalid default_tag_ids")
			return
		}
		if tagIDs == nil {
			tagIDs = []int64{}
		}
		b.add("default_tag_ids", tagIDs)
		tagChange = true
	}

	if b.empty() {
		writeJSON(w, http.StatusOK, c.DTO())
		return
	}

	tx, err := a.db.Begin(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	defer func() { _ = tx.Rollback(r.Context()) }()

	q := `UPDATE source_channels SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d RETURNING ", len(b.args)+1) + channelCols
	b.args = append(b.args, id)
	updated, err := scanChannel(tx.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if tagChange {
		missing, err := a.setDefaultTagLinks(r.Context(), tx, id, tagIDs)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "db error")
			return
		}
		if missing != nil {
			writeError(w, http.StatusBadRequest, "unknown tag ids: "+formatInt64List(missing))
			return
		}
	}
	if err := tx.Commit(r.Context()); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.DTO())
}

func (a *App) handleDeleteChannel(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "channelID")
	if !ok {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	c, err := a.loadChannel(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	var active int64
	if err := a.db.QueryRow(r.Context(),
		`SELECT count(id) FROM posts WHERE source_channel_id=$1 AND state NOT IN ('published','rejected')`,
		id).Scan(&active); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if active > 0 {
		writeError(w, http.StatusConflict, fmt.Sprintf(
			"channel has %d active post(s) (not yet published or rejected). "+
				"Reject or wait for them to complete before deleting the channel.", active))
		return
	}
	if _, err := a.db.Exec(r.Context(), `DELETE FROM source_channels WHERE id=$1`, id); err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeNoContent(w)
}

// ── AI settings (sub-resource of source channels) ────────────────────────────

func (a *App) handleGetAISettings(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "channelID")
	if !ok {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	c, err := a.loadChannel(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	writeJSON(w, http.StatusOK, c.AISettings())
}

func (a *App) handleUpdateAISettings(w http.ResponseWriter, r *http.Request) {
	id, ok := urlInt64(r, "channelID")
	if !ok {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	c, err := a.loadChannel(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	body, err := decodePatchBody(r)
	if err != nil {
		writeError(w, http.StatusUnprocessableEntity, "invalid body")
		return
	}
	b := &setBuilder{}
	_ = b.addBool(body, "ai_enabled", "ai_enabled")
	_ = b.addStr(body, "ai_mode", "ai_mode")
	_ = b.addStr(body, "ai_target_language", "ai_target_language")
	_ = b.addStr(body, "ai_tone_prompt", "ai_tone_prompt")
	_ = b.addStr(body, "ai_custom_system_prompt", "ai_custom_system_prompt")
	_ = b.addBool(body, "watermark_enabled", "watermark_enabled")
	_ = b.addStr(body, "watermark_text", "watermark_text")
	_ = b.addBool(body, "strip_source_tags", "strip_source_tags")
	if b.empty() {
		writeJSON(w, http.StatusOK, c.AISettings())
		return
	}
	q := `UPDATE source_channels SET ` + b.clause() + fmt.Sprintf(" WHERE id=$%d RETURNING ", len(b.args)+1) + channelCols
	b.args = append(b.args, id)
	updated, err := scanChannel(a.db.QueryRow(r.Context(), q, b.args...))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	writeJSON(w, http.StatusOK, updated.AISettings())
}

func (a *App) handleTestAITransform(w http.ResponseWriter, r *http.Request) {
	if !a.cfg.AIEnabled {
		writeError(w, http.StatusBadRequest, "AI transformation is globally disabled")
		return
	}
	if a.cfg.AIAPIKey == "" {
		writeError(w, http.StatusBadRequest, "AI_API_KEY is not configured")
		return
	}
	id, ok := urlInt64(r, "channelID")
	if !ok {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	c, err := a.loadChannel(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "db error")
		return
	}
	if c == nil {
		writeError(w, http.StatusNotFound, "source channel not found")
		return
	}
	var in struct {
		Text               string  `json:"text"`
		Mode               *string `json:"mode"`
		TargetLanguage     *string `json:"target_language"`
		TonePrompt         *string `json:"tone_prompt"`
		CustomSystemPrompt *string `json:"custom_system_prompt"`
	}
	if err := decodeJSON(r, &in); err != nil || in.Text == "" {
		writeError(w, http.StatusUnprocessableEntity, "text is required")
		return
	}
	mode := "translate"
	if in.Mode != nil && *in.Mode != "" {
		mode = *in.Mode
	}
	target := derefStr(in.TargetLanguage)
	if target == "" {
		target = derefStr(c.AITargetLanguage)
	}
	tone := derefStr(in.TonePrompt)
	if tone == "" {
		tone = derefStr(c.AITonePrompt)
	}
	custom := derefStr(in.CustomSystemPrompt)
	if custom == "" {
		custom = derefStr(c.AICustomSystemPrompt)
	}

	result, err := a.transformText(r.Context(), in.Text, mode, target, tone, custom)
	if err != nil {
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"original":          in.Text,
		"transformed":       result.Text,
		"model":             result.Model,
		"prompt_tokens":     result.PromptTokens,
		"completion_tokens": result.CompletionTokens,
		"latency_ms":        result.LatencyMs,
	})
}
