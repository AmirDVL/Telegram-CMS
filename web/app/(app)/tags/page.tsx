"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Tag } from "@/lib/types";

export default function TagsPage() {
  const [items, setItems] = useState<Tag[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    apiFetch<Tag[]>("/tags")
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));

  useEffect(() => {
    refresh();
  }, []);

  const [slug, setSlug] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await apiFetch("/tags", {
      method: "POST",
      body: JSON.stringify({ slug, label, color: color || null }),
    });
    setSlug("");
    setLabel("");
    setColor("");
    refresh();
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Tag vocabulary</h1>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <form onSubmit={submit} className="flex flex-wrap gap-2 rounded border border-slate-200 bg-white p-3 text-sm">
        <input className="rounded border border-slate-300 px-2 py-1" placeholder="slug" value={slug} onChange={(e) => setSlug(e.target.value)} required />
        <input className="rounded border border-slate-300 px-2 py-1" placeholder="label" value={label} onChange={(e) => setLabel(e.target.value)} required />
        <input className="rounded border border-slate-300 px-2 py-1" placeholder="#hex color" value={color} onChange={(e) => setColor(e.target.value)} />
        <button className="rounded bg-slate-800 px-3 py-1 text-white hover:bg-slate-700">Add tag</button>
      </form>
      <div className="flex flex-wrap gap-2">
        {items.map((t) => (
          <span key={t.id} className="flex items-center gap-2 rounded-full border border-slate-300 px-3 py-1 text-sm">
            <span className="h-3 w-3 rounded-full" style={{ background: t.color || "#888" }} />
            {t.label}
            <code className="text-xs text-slate-400">#{t.slug}</code>
            <button
              onClick={() => apiFetch(`/tags/${t.id}`, { method: "DELETE" }).then(refresh)}
              className="text-xs text-red-600 hover:underline"
            >
              ×
            </button>
          </span>
        ))}
      </div>
    </div>
  );
}
