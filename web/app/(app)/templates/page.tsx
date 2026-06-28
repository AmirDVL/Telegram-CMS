"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Template } from "@/lib/types";

export default function TemplatesPage() {
  const [items, setItems] = useState<Template[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = () =>
    apiFetch<Template[]>("/templates")
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Templates</h1>
      <p className="text-sm text-slate-500">
        Placeholders: <code>{"{{ text }}"}</code>, <code>{"{{ source_label }}"}</code>, <code>{"{{ tags }}"}</code>
      </p>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <TemplateForm onCreated={refresh} />
      <div className="grid gap-2">
        {items.map((t) => (
          <div key={t.id} className="rounded border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <span className="font-medium">{t.name}</span>
              <button
                onClick={() => apiFetch(`/templates/${t.id}`, { method: "DELETE" }).then(refresh)}
                className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
              >
                Delete
              </button>
            </div>
            <pre className="mt-2 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs">{t.body}</pre>
          </div>
        ))}
      </div>
    </div>
  );
}

function TemplateForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [body, setBody] = useState(
    "{% if tags %}{{ tags }}\n{% endif %}{{ text }}\n\n— {{ source_label }}"
  );
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await apiFetch("/templates", { method: "POST", body: JSON.stringify({ name, body }) });
    setName("");
    onCreated();
  };
  return (
    <form onSubmit={submit} className="space-y-2 rounded border border-slate-200 bg-white p-3 text-sm">
      <input className="w-full rounded border border-slate-300 px-2 py-1" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} required />
      <textarea className="h-28 w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs" value={body} onChange={(e) => setBody(e.target.value)} required />
      <button className="rounded bg-slate-800 px-3 py-1 text-white hover:bg-slate-700">Add template</button>
    </form>
  );
}
