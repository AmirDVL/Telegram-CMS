"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { SourceChannel, Tag, Template, Policy } from "@/lib/types";

export default function SourcesPage() {
  const [items, setItems] = useState<SourceChannel[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    Promise.all([
      apiFetch<SourceChannel[]>("/source-channels"),
      apiFetch<Tag[]>("/tags"),
      apiFetch<Template[]>("/templates"),
    ])
      .then(([c, t, tpl]) => {
        setItems(c);
        setTags(t);
        setTemplates(tpl);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Source channels</h1>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <ChannelForm tags={tags} templates={templates} onCreated={refresh} />
      <div className="grid gap-2">
        {items.map((c) => (
          <div key={c.id} className="flex items-center justify-between rounded border border-slate-200 bg-white p-3">
            <div>
              <div className="font-medium">{c.title}</div>
              <div className="text-xs text-slate-500">
                id: {c.telegram_channel_id} · @{c.username || "—"} · policy: {c.policy} ·
                enabled: {c.ingestion_enabled ? "yes" : "no"} · label: {c.source_label || "—"}
              </div>
            </div>
            <button
              onClick={() => apiFetch(`/source-channels/${c.id}`, { method: "DELETE" }).then(refresh)}
              className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
            >
              Delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChannelForm({
  tags,
  templates,
  onCreated,
}: {
  tags: Tag[];
  templates: Template[];
  onCreated: () => void;
}) {
  const [tgId, setTgId] = useState("");
  const [title, setTitle] = useState("");
  const [username, setUsername] = useState("");
  const [policy, setPolicy] = useState<Policy>("queue");
  const [label, setLabel] = useState("");
  const [tpl, setTpl] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await apiFetch("/source-channels", {
      method: "POST",
      body: JSON.stringify({
        telegram_channel_id: Number(tgId),
        title,
        username: username || null,
        policy,
        source_label: label || null,
        normalization_template_id: tpl ? Number(tpl) : null,
      }),
    });
    setTgId("");
    setTitle("");
    setUsername("");
    setLabel("");
    onCreated();
  };

  return (
    <form onSubmit={submit} className="grid grid-cols-2 gap-2 rounded border border-slate-200 bg-white p-3 text-sm">
      <input className="rounded border border-slate-300 px-2 py-1" placeholder="Telegram channel id" value={tgId} onChange={(e) => setTgId(e.target.value)} required />
      <input className="rounded border border-slate-300 px-2 py-1" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />
      <input className="rounded border border-slate-300 px-2 py-1" placeholder="@username" value={username} onChange={(e) => setUsername(e.target.value)} />
      <input className="rounded border border-slate-300 px-2 py-1" placeholder="Source label" value={label} onChange={(e) => setLabel(e.target.value)} />
      <select className="rounded border border-slate-300 px-2 py-1" value={policy} onChange={(e) => setPolicy(e.target.value as Policy)}>
        <option value="queue">queue</option>
        <option value="auto">auto</option>
      </select>
      <select className="rounded border border-slate-300 px-2 py-1" value={tpl} onChange={(e) => setTpl(e.target.value)}>
        <option value="">no template</option>
        {templates.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <button className="col-span-2 rounded bg-slate-800 px-3 py-1 text-white hover:bg-slate-700">Add channel</button>
    </form>
  );
}
