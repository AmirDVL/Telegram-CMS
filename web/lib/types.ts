export type Role = "editor" | "admin" | "super_admin";
export type Policy = "auto" | "queue";
export type PostState =
  | "pending"
  | "approved"
  | "scheduled"
  | "published"
  | "rejected"
  | "publishing"
  | "publish_failed";
export type EventAction =
  | "ingested"
  | "edited"
  | "approved"
  | "rejected"
  | "scheduled"
  | "published"
  | "publish_failed"
  | "duplicate"
  | "media_omitted"
  | "draft_posted"
  | "ai_transformed"
  | "ai_failed";
export type AIMode = "off" | "translate" | "summarize" | "retone" | "custom";

export interface Admin {
  id: number;
  username: string;
  role: Role;
  tg_user_id: number | null;
  tenant_id: number | null;
  created_at: string;
  disabled_at: string | null;
}

export interface Tag {
  id: number;
  slug: string;
  label: string;
  color: string | null;
  created_at: string;
}

export interface Template {
  id: number;
  name: string;
  body: string;
  created_at: string;
}

export interface AISettings {
  ai_enabled: boolean;
  ai_mode: AIMode;
  ai_target_language: string | null;
  ai_tone_prompt: string | null;
  ai_custom_system_prompt: string | null;
  watermark_enabled: boolean;
  watermark_text: string | null;
  strip_source_tags: boolean;
}

export interface SourceChannel extends AISettings {
  id: number;
  telegram_channel_id: number;
  title: string;
  username: string | null;
  ingestion_enabled: boolean;
  policy: Policy;
  default_tag_ids: number[];
  normalization_template_id: number | null;
  max_media_size_bytes: number;
  source_label: string | null;
  created_at: string;
}

export interface MediaRef {
  type: string;
  file: string;
  size?: number;
  mime?: string;
  omitted?: boolean;
}

export interface Post {
  id: number;
  source_channel_id: number;
  source_message_id: number;
  raw_text: string | null;
  raw_media_refs: MediaRef[];
  received_at: string;
  state: PostState;
  normalized_text: string | null;
  ai_transformed_text: string | null;
  media_paths: unknown[];
  tag_ids: number[];
  scheduled_for: string | null;
  published_message_id: number | null;
  published_at: string | null;
  dedupe_hash: string | null;
  draft_message_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface PostEvent {
  id: number;
  post_id: number;
  actor_admin_id: number | null;
  action: EventAction;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface TokenOut {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Tenant {
  id: number;
  slug: string;
  name: string;
  bot_token: string | null;
  destination_channel_id: number | null;
  editor_group_id: number | null;
  ai_enabled: boolean;
  ai_mode: AIMode;
  ai_target_language: string | null;
  ai_tone_prompt: string | null;
  ai_custom_system_prompt: string | null;
  watermark_enabled: boolean;
  watermark_text: string | null;
  strip_source_tags: boolean;
  created_at: string;
  disabled_at: string | null;
}

export interface AITestRequest {
  text: string;
  mode: AIMode;
  target_language?: string;
  tone_prompt?: string;
  custom_system_prompt?: string;
}

export interface AITestResponse {
  original: string;
  transformed: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
}
