package main

import (
	"encoding/json"
	"time"
)

// ── Enums (mirror shared/enums.py) ───────────────────────────────────────────

type Role string

const (
	RoleEditor     Role = "editor"
	RoleAdmin      Role = "admin"
	RoleSuperAdmin Role = "super_admin"
)

func roleRank(r Role) int {
	switch r {
	case RoleEditor:
		return 0
	case RoleAdmin:
		return 1
	case RoleSuperAdmin:
		return 2
	default:
		return -1
	}
}

func roleAtLeast(held, required Role) bool {
	hr, rr := roleRank(held), roleRank(required)
	return hr >= 0 && rr >= 0 && hr >= rr
}

func validRole(r string) bool { return roleRank(Role(r)) >= 0 }

// scannable is satisfied by both pgx.Row and pgx.Rows.
type scannable interface {
	Scan(dest ...any) error
}

// jsonOrEmpty returns b, defaulting to the given literal (e.g. "[]" or "{}")
// when the column was NULL/empty so JSON output matches pydantic defaults.
func jsonOrEmpty(b json.RawMessage, def string) json.RawMessage {
	if len(b) == 0 {
		return json.RawMessage(def)
	}
	return b
}

func int64Slice(s []int64) []int64 {
	if s == nil {
		return []int64{}
	}
	return s
}

// ── Admin ────────────────────────────────────────────────────────────────────

const adminCols = `id, username, password_hash, role, tg_user_id, created_at, disabled_at`

type adminRow struct {
	ID           int64
	Username     string
	PasswordHash string
	Role         string
	TgUserID     *int64
	CreatedAt    time.Time
	DisabledAt   *time.Time
}

func scanAdmin(r scannable) (*adminRow, error) {
	a := &adminRow{}
	err := r.Scan(&a.ID, &a.Username, &a.PasswordHash, &a.Role, &a.TgUserID, &a.CreatedAt, &a.DisabledAt)
	if err != nil {
		return nil, err
	}
	return a, nil
}

type AdminOut struct {
	ID         int64      `json:"id"`
	Username   string     `json:"username"`
	Role       string     `json:"role"`
	TgUserID   *int64     `json:"tg_user_id"`
	CreatedAt  time.Time  `json:"created_at"`
	DisabledAt *time.Time `json:"disabled_at"`
}

func (a *adminRow) DTO() AdminOut {
	return AdminOut{
		ID: a.ID, Username: a.Username, Role: a.Role,
		TgUserID: a.TgUserID,
		CreatedAt: a.CreatedAt, DisabledAt: a.DisabledAt,
	}
}

// ── Tag ──────────────────────────────────────────────────────────────────────

const tagCols = `id, slug, label, color, created_at`

type tagRow struct {
	ID        int64
	Slug      string
	Label     string
	Color     *string
	CreatedAt time.Time
}

func scanTag(r scannable) (*tagRow, error) {
	t := &tagRow{}
	err := r.Scan(&t.ID, &t.Slug, &t.Label, &t.Color, &t.CreatedAt)
	if err != nil {
		return nil, err
	}
	return t, nil
}

type TagOut struct {
	ID        int64     `json:"id"`
	Slug      string    `json:"slug"`
	Label     string    `json:"label"`
	Color     *string   `json:"color"`
	CreatedAt time.Time `json:"created_at"`
}

func (t *tagRow) DTO() TagOut {
	return TagOut{ID: t.ID, Slug: t.Slug, Label: t.Label, Color: t.Color, CreatedAt: t.CreatedAt}
}

// ── Template ─────────────────────────────────────────────────────────────────

const templateCols = `id, name, body, created_at`

type templateRow struct {
	ID        int64
	Name      string
	Body      string
	CreatedAt time.Time
}

func scanTemplate(r scannable) (*templateRow, error) {
	t := &templateRow{}
	err := r.Scan(&t.ID, &t.Name, &t.Body, &t.CreatedAt)
	if err != nil {
		return nil, err
	}
	return t, nil
}

type TemplateOut struct {
	ID        int64     `json:"id"`
	Name      string    `json:"name"`
	Body      string    `json:"body"`
	CreatedAt time.Time `json:"created_at"`
}

func (t *templateRow) DTO() TemplateOut {
	return TemplateOut{ID: t.ID, Name: t.Name, Body: t.Body, CreatedAt: t.CreatedAt}
}

// ── SourceChannel ────────────────────────────────────────────────────────────

const channelCols = `id, telegram_channel_id, title, username, ingestion_enabled, policy, ` +
	`default_tag_ids, normalization_template_id, max_media_size_bytes, source_label, ` +
	`ai_enabled, ai_mode, ai_target_language, ai_tone_prompt, ai_custom_system_prompt, ` +
	`watermark_enabled, watermark_text, strip_source_tags, created_at`

type channelRow struct {
	ID                      int64
	TelegramChannelID       int64
	Title                   string
	Username                *string
	IngestionEnabled        bool
	Policy                  string
	DefaultTagIDs           []int64
	NormalizationTemplateID *int64
	MaxMediaSizeBytes       int64
	SourceLabel             *string
	AIEnabled               bool
	AIMode                  string
	AITargetLanguage        *string
	AITonePrompt            *string
	AICustomSystemPrompt    *string
	WatermarkEnabled        bool
	WatermarkText           *string
	StripSourceTags         bool
	CreatedAt               time.Time
}

func scanChannel(r scannable) (*channelRow, error) {
	c := &channelRow{}
	err := r.Scan(
		&c.ID, &c.TelegramChannelID, &c.Title, &c.Username, &c.IngestionEnabled, &c.Policy,
		&c.DefaultTagIDs, &c.NormalizationTemplateID, &c.MaxMediaSizeBytes, &c.SourceLabel,
		&c.AIEnabled, &c.AIMode, &c.AITargetLanguage, &c.AITonePrompt, &c.AICustomSystemPrompt,
		&c.WatermarkEnabled, &c.WatermarkText, &c.StripSourceTags, &c.CreatedAt,
	)
	if err != nil {
		return nil, err
	}
	return c, nil
}

type SourceChannelOut struct {
	ID                      int64     `json:"id"`
	TelegramChannelID       int64     `json:"telegram_channel_id"`
	Title                   string    `json:"title"`
	Username                *string   `json:"username"`
	IngestionEnabled        bool      `json:"ingestion_enabled"`
	Policy                  string    `json:"policy"`
	DefaultTagIDs           []int64   `json:"default_tag_ids"`
	NormalizationTemplateID *int64    `json:"normalization_template_id"`
	MaxMediaSizeBytes       int64     `json:"max_media_size_bytes"`
	SourceLabel             *string   `json:"source_label"`
	AIEnabled               bool      `json:"ai_enabled"`
	AIMode                  string    `json:"ai_mode"`
	AITargetLanguage        *string   `json:"ai_target_language"`
	AITonePrompt            *string   `json:"ai_tone_prompt"`
	AICustomSystemPrompt    *string   `json:"ai_custom_system_prompt"`
	WatermarkEnabled        bool      `json:"watermark_enabled"`
	WatermarkText           *string   `json:"watermark_text"`
	StripSourceTags         bool      `json:"strip_source_tags"`
	CreatedAt               time.Time `json:"created_at"`
}

func (c *channelRow) DTO() SourceChannelOut {
	return SourceChannelOut{
		ID: c.ID, TelegramChannelID: c.TelegramChannelID, Title: c.Title, Username: c.Username,
		IngestionEnabled: c.IngestionEnabled, Policy: c.Policy,
		DefaultTagIDs: int64Slice(c.DefaultTagIDs), NormalizationTemplateID: c.NormalizationTemplateID,
		MaxMediaSizeBytes: c.MaxMediaSizeBytes, SourceLabel: c.SourceLabel,
		AIEnabled: c.AIEnabled, AIMode: c.AIMode, AITargetLanguage: c.AITargetLanguage,
		AITonePrompt: c.AITonePrompt, AICustomSystemPrompt: c.AICustomSystemPrompt,
		WatermarkEnabled: c.WatermarkEnabled, WatermarkText: c.WatermarkText,
		StripSourceTags: c.StripSourceTags, CreatedAt: c.CreatedAt,
	}
}

type AISettingsOut struct {
	AIEnabled            bool    `json:"ai_enabled"`
	AIMode               string  `json:"ai_mode"`
	AITargetLanguage     *string `json:"ai_target_language"`
	AITonePrompt         *string `json:"ai_tone_prompt"`
	AICustomSystemPrompt *string `json:"ai_custom_system_prompt"`
	WatermarkEnabled     bool    `json:"watermark_enabled"`
	WatermarkText        *string `json:"watermark_text"`
	StripSourceTags      bool    `json:"strip_source_tags"`
}

func (c *channelRow) AISettings() AISettingsOut {
	return AISettingsOut{
		AIEnabled: c.AIEnabled, AIMode: c.AIMode, AITargetLanguage: c.AITargetLanguage,
		AITonePrompt: c.AITonePrompt, AICustomSystemPrompt: c.AICustomSystemPrompt,
		WatermarkEnabled: c.WatermarkEnabled, WatermarkText: c.WatermarkText,
		StripSourceTags: c.StripSourceTags,
	}
}

// ── Post ─────────────────────────────────────────────────────────────────────

const postCols = `id, source_channel_id, source_message_id, raw_text, raw_media_refs, received_at, ` +
	`state, normalized_text, ai_transformed_text, media_paths, tag_ids, scheduled_for, ` +
	`published_message_id, published_at, dedupe_hash, created_at, updated_at`

type postRow struct {
	ID                 int64
	SourceChannelID    int64
	SourceMessageID    int64
	RawText            *string
	RawMediaRefs       json.RawMessage
	ReceivedAt         time.Time
	State              string
	NormalizedText     *string
	AITransformedText  *string
	MediaPaths         json.RawMessage
	TagIDs             []int64
	ScheduledFor       *time.Time
	PublishedMessageID *int64
	PublishedAt        *time.Time
	DedupeHash         *string
	CreatedAt          time.Time
	UpdatedAt          time.Time
}

func scanPost(r scannable) (*postRow, error) {
	p := &postRow{}
	err := r.Scan(
		&p.ID, &p.SourceChannelID, &p.SourceMessageID, &p.RawText, &p.RawMediaRefs, &p.ReceivedAt,
		&p.State, &p.NormalizedText, &p.AITransformedText, &p.MediaPaths, &p.TagIDs, &p.ScheduledFor,
		&p.PublishedMessageID, &p.PublishedAt, &p.DedupeHash, &p.CreatedAt, &p.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return p, nil
}

type PostOut struct {
	ID                 int64           `json:"id"`
	SourceChannelID    int64           `json:"source_channel_id"`
	SourceMessageID    int64           `json:"source_message_id"`
	RawText            *string         `json:"raw_text"`
	RawMediaRefs       json.RawMessage `json:"raw_media_refs"`
	ReceivedAt         time.Time       `json:"received_at"`
	State              string          `json:"state"`
	NormalizedText     *string         `json:"normalized_text"`
	AITransformedText  *string         `json:"ai_transformed_text"`
	MediaPaths         json.RawMessage `json:"media_paths"`
	TagIDs             []int64         `json:"tag_ids"`
	ScheduledFor       *time.Time      `json:"scheduled_for"`
	PublishedMessageID *int64          `json:"published_message_id"`
	PublishedAt        *time.Time      `json:"published_at"`
	DedupeHash         *string         `json:"dedupe_hash"`
	CreatedAt          time.Time       `json:"created_at"`
	UpdatedAt          time.Time       `json:"updated_at"`
}

func (p *postRow) DTO() PostOut {
	return PostOut{
		ID: p.ID, SourceChannelID: p.SourceChannelID, SourceMessageID: p.SourceMessageID,
		RawText: p.RawText, RawMediaRefs: jsonOrEmpty(p.RawMediaRefs, "[]"), ReceivedAt: p.ReceivedAt,
		State: p.State, NormalizedText: p.NormalizedText, AITransformedText: p.AITransformedText,
		MediaPaths: jsonOrEmpty(p.MediaPaths, "[]"), TagIDs: int64Slice(p.TagIDs),
		ScheduledFor: p.ScheduledFor, PublishedMessageID: p.PublishedMessageID,
		PublishedAt: p.PublishedAt, DedupeHash: p.DedupeHash,
		CreatedAt: p.CreatedAt, UpdatedAt: p.UpdatedAt,
	}
}

// ── PostEvent ────────────────────────────────────────────────────────────────

const postEventCols = `id, post_id, actor_admin_id, action, payload, created_at`

type postEventRow struct {
	ID           int64
	PostID       int64
	ActorAdminID *int64
	Action       string
	Payload      json.RawMessage
	CreatedAt    time.Time
}

func scanPostEvent(r scannable) (*postEventRow, error) {
	e := &postEventRow{}
	err := r.Scan(&e.ID, &e.PostID, &e.ActorAdminID, &e.Action, &e.Payload, &e.CreatedAt)
	if err != nil {
		return nil, err
	}
	return e, nil
}

type PostEventOut struct {
	ID           int64           `json:"id"`
	PostID       int64           `json:"post_id"`
	ActorAdminID *int64          `json:"actor_admin_id"`
	Action       string          `json:"action"`
	Payload      json.RawMessage `json:"payload"`
	CreatedAt    time.Time       `json:"created_at"`
}

func (e *postEventRow) DTO() PostEventOut {
	return PostEventOut{
		ID: e.ID, PostID: e.PostID, ActorAdminID: e.ActorAdminID, Action: e.Action,
		Payload: jsonOrEmpty(e.Payload, "{}"), CreatedAt: e.CreatedAt,
	}
}

// ── Misc response shapes ─────────────────────────────────────────────────────

type TokenOut struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	TokenType    string `json:"token_type"`
}

type Paginated struct {
	Items  any   `json:"items"`
	Total  int64 `json:"total"`
	Limit  int   `json:"limit"`
	Offset int   `json:"offset"`
}

type HealthOut struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}
