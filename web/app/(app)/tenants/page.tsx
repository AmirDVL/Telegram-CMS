"use client";

import { useEffect, useState } from "react";
import { fetchTenants, createTenant, updateTenant, disableTenant } from "@/lib/api";
import type { Tenant, AIMode } from "@/lib/types";

export default function TenantsPage() {
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null);

  const loadTenants = async () => {
    try {
      const data = await fetchTenants();
      setTenants(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load tenants");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTenants();
  }, []);

  const handleCreate = () => {
    setEditingTenant(null);
    setShowModal(true);
  };

  const handleEdit = (tenant: Tenant) => {
    setEditingTenant(tenant);
    setShowModal(true);
  };

  const handleDisable = async (tenant: Tenant) => {
    if (!confirm(`Disable tenant "${tenant.name}"?`)) return;
    try {
      await disableTenant(tenant.id);
      await loadTenants();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to disable tenant");
    }
  };

  const handleSave = async (data: Partial<Tenant>) => {
    try {
      if (editingTenant) {
        await updateTenant(editingTenant.id, data);
      } else {
        await createTenant(data);
      }
      setShowModal(false);
      await loadTenants();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save tenant");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Tenants</h1>
        <button
          onClick={handleCreate}
          className="rounded bg-slate-800 px-3 py-1 text-sm text-white hover:bg-slate-700"
        >
          Create Tenant
        </button>
      </div>
      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      {loading ? (
        <div className="text-slate-400">Loading…</div>
      ) : tenants.length === 0 ? (
        <div className="text-slate-400">No tenants yet.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50">
              <tr>
                <th className="px-3 py-2 text-left">Slug</th>
                <th className="px-3 py-2 text-left">Name</th>
                <th className="px-3 py-2 text-left">Bot Token</th>
                <th className="px-3 py-2 text-left">Dest Channel</th>
                <th className="px-3 py-2 text-left">Editor Group</th>
                <th className="px-3 py-2 text-left">AI</th>
                <th className="px-3 py-2 text-left">Watermark</th>
                <th className="px-3 py-2 text-left">Created</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {tenants.map((t) => (
                <tr key={t.id} className="border-b border-slate-100">
                  <td className="px-3 py-2 font-mono text-xs">{t.slug}</td>
                  <td className="px-3 py-2">{t.name}</td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {t.bot_token ? `${t.bot_token.slice(0, 6)}...` : "—"}
                  </td>
                  <td className="px-3 py-2">{t.destination_channel_id ?? "—"}</td>
                  <td className="px-3 py-2">{t.editor_group_id ?? "—"}</td>
                  <td className="px-3 py-2">{t.ai_enabled ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{t.watermark_enabled ? "Yes" : "No"}</td>
                  <td className="px-3 py-2">{new Date(t.created_at).toLocaleDateString()}</td>
                  <td className="px-3 py-2">
                    {t.disabled_at ? (
                      <span className="text-red-600">Disabled</span>
                    ) : (
                      <span className="text-green-600">Active</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      <button
                        onClick={() => handleEdit(t)}
                        className="text-blue-600 hover:underline"
                      >
                        Edit
                      </button>
                      {!t.disabled_at && (
                        <button
                          onClick={() => handleDisable(t)}
                          className="text-red-600 hover:underline"
                        >
                          Disable
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {showModal && (
        <TenantModal
          tenant={editingTenant}
          onClose={() => setShowModal(false)}
          onSave={handleSave}
        />
      )}
    </div>
  );
}

function TenantModal({
  tenant,
  onClose,
  onSave,
}: {
  tenant: Tenant | null;
  onClose: () => void;
  onSave: (data: Partial<Tenant>) => Promise<void>;
}) {
  const [form, setForm] = useState<Partial<Tenant>>({
    slug: tenant?.slug ?? "",
    name: tenant?.name ?? "",
    bot_token: "",
    destination_channel_id: tenant?.destination_channel_id ?? null,
    editor_group_id: tenant?.editor_group_id ?? null,
    ai_enabled: tenant?.ai_enabled ?? false,
    ai_mode: (tenant?.ai_mode ?? "off") as AIMode,
    ai_target_language: tenant?.ai_target_language ?? "",
    ai_tone_prompt: tenant?.ai_tone_prompt ?? "",
    ai_custom_system_prompt: tenant?.ai_custom_system_prompt ?? "",
    watermark_enabled: tenant?.watermark_enabled ?? false,
    watermark_text: tenant?.watermark_text ?? "",
    strip_source_tags: tenant?.strip_source_tags ?? false,
    ai_model: tenant?.ai_model ?? null,
    ai_max_tokens: tenant?.ai_max_tokens ?? null,
    ai_timeout_seconds: tenant?.ai_timeout_seconds ?? null,
    dedupe_lookback_days: tenant?.dedupe_lookback_days ?? null,
    publish_spacing_seconds: tenant?.publish_spacing_seconds ?? null,
    media_max_size_bytes: tenant?.media_max_size_bytes ?? null,
  });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const setField = <K extends keyof Partial<Tenant>>(key: K, value: Partial<Tenant>[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const payload: Partial<Tenant> = { ...form };
      // On edit: empty bot_token means "leave unchanged" — omit from payload.
      if (tenant && !payload.bot_token) {
        delete payload.bot_token;
      }
      // Convert empty strings to null for optional string fields.
      (
        [
          "ai_target_language",
          "ai_tone_prompt",
          "ai_custom_system_prompt",
          "watermark_text",
          "ai_model",
        ] as const
      ).forEach((k) => {
        if (payload[k] === "") (payload as Record<string, unknown>)[k] = null;
      });
      await onSave(payload);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const inp =
    "w-full rounded border border-slate-300 px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-slate-400";

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-16">
      <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-white shadow-lg">
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="font-semibold">{tenant ? "Edit Tenant" : "Create Tenant"}</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            ✕
          </button>
        </div>
        <form onSubmit={handleSubmit} className="max-h-[70vh] space-y-3 overflow-y-auto p-4">
          {formError && (
            <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {formError}
            </div>
          )}

          {/* Core identity */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Slug <span className="text-red-500">*</span>
              </label>
              <input
                className={inp}
                value={form.slug ?? ""}
                onChange={(e) => setField("slug", e.target.value)}
                placeholder="my-tenant"
                required
                disabled={!!tenant}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Name <span className="text-red-500">*</span>
              </label>
              <input
                className={inp}
                value={form.name ?? ""}
                onChange={(e) => setField("name", e.target.value)}
                placeholder="My Tenant"
                required
              />
            </div>
          </div>

          {/* Telegram credentials */}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">Bot Token</label>
            <input
              type="password"
              className={inp}
              value={form.bot_token ?? ""}
              onChange={(e) => setField("bot_token", e.target.value)}
              placeholder={tenant ? "leave blank to keep unchanged" : "123456:ABC..."}
              autoComplete="new-password"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Destination Channel ID
              </label>
              <input
                className={inp}
                type="number"
                value={form.destination_channel_id ?? ""}
                onChange={(e) =>
                  setField(
                    "destination_channel_id",
                    e.target.value ? Number(e.target.value) : null,
                  )
                }
                placeholder="-100…"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Editor Group ID
              </label>
              <input
                className={inp}
                type="number"
                value={form.editor_group_id ?? ""}
                onChange={(e) =>
                  setField("editor_group_id", e.target.value ? Number(e.target.value) : null)
                }
                placeholder="-100…"
              />
            </div>
          </div>

          {/* AI settings */}
          <div className="border-t border-slate-100 pt-2">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              AI Settings
            </p>
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.ai_enabled ?? false}
                  onChange={(e) => setField("ai_enabled", e.target.checked)}
                />
                AI Enabled
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.watermark_enabled ?? false}
                  onChange={(e) => setField("watermark_enabled", e.target.checked)}
                />
                Watermark
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={form.strip_source_tags ?? false}
                  onChange={(e) => setField("strip_source_tags", e.target.checked)}
                />
                Strip Tags
              </label>
            </div>
            <div className="mt-2 grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">AI Mode</label>
                <select
                  className={inp}
                  value={form.ai_mode ?? "off"}
                  onChange={(e) => setField("ai_mode", e.target.value as AIMode)}
                >
                  <option value="off">off</option>
                  <option value="translate">translate</option>
                  <option value="summarize">summarize</option>
                  <option value="retone">retone</option>
                  <option value="custom">custom</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  Target Language
                </label>
                <input
                  className={inp}
                  value={form.ai_target_language ?? ""}
                  onChange={(e) => setField("ai_target_language", e.target.value)}
                  placeholder="en"
                />
              </div>
            </div>
            <div className="mt-2">
              <label className="mb-1 block text-xs font-medium text-slate-600">Tone Prompt</label>
              <input
                className={inp}
                value={form.ai_tone_prompt ?? ""}
                onChange={(e) => setField("ai_tone_prompt", e.target.value)}
                placeholder="Formal and concise"
              />
            </div>
            <div className="mt-2">
              <label className="mb-1 block text-xs font-medium text-slate-600">
                Custom System Prompt
              </label>
              <textarea
                className={inp}
                rows={2}
                value={form.ai_custom_system_prompt ?? ""}
                onChange={(e) => setField("ai_custom_system_prompt", e.target.value)}
                placeholder="You are…"
              />
            </div>
            <div className="mt-2">
              <label className="mb-1 block text-xs font-medium text-slate-600">Watermark Text</label>
              <input
                className={inp}
                value={form.watermark_text ?? ""}
                onChange={(e) => setField("watermark_text", e.target.value)}
                placeholder="© My Channel"
              />
            </div>
          </div>

          {/* Per-tenant config overrides */}
          <div className="border-t border-slate-100 pt-2">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
              Config Overrides <span className="font-normal normal-case">(blank = use global)</span>
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">AI Model</label>
                <input
                  className={inp}
                  value={form.ai_model ?? ""}
                  onChange={(e) => setField("ai_model", e.target.value || null)}
                  placeholder="gpt-4o"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  AI Max Tokens
                </label>
                <input
                  className={inp}
                  type="number"
                  value={form.ai_max_tokens ?? ""}
                  onChange={(e) =>
                    setField("ai_max_tokens", e.target.value ? Number(e.target.value) : null)
                  }
                  placeholder="4000"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  AI Timeout (s)
                </label>
                <input
                  className={inp}
                  type="number"
                  value={form.ai_timeout_seconds ?? ""}
                  onChange={(e) =>
                    setField("ai_timeout_seconds", e.target.value ? Number(e.target.value) : null)
                  }
                  placeholder="30"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  Dedupe Lookback (days)
                </label>
                <input
                  className={inp}
                  type="number"
                  value={form.dedupe_lookback_days ?? ""}
                  onChange={(e) =>
                    setField("dedupe_lookback_days", e.target.value ? Number(e.target.value) : null)
                  }
                  placeholder="7"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  Publish Spacing (s)
                </label>
                <input
                  className={inp}
                  type="number"
                  step="0.1"
                  value={form.publish_spacing_seconds ?? ""}
                  onChange={(e) =>
                    setField(
                      "publish_spacing_seconds",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  placeholder="2.0"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-slate-600">
                  Media Max Size (bytes)
                </label>
                <input
                  className={inp}
                  type="number"
                  value={form.media_max_size_bytes ?? ""}
                  onChange={(e) =>
                    setField(
                      "media_max_size_bytes",
                      e.target.value ? Number(e.target.value) : null,
                    )
                  }
                  placeholder="2147483648"
                />
              </div>
            </div>
          </div>
        </form>
        <div className="flex justify-end gap-2 border-t border-slate-200 px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="rounded bg-slate-800 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : tenant ? "Save Changes" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
