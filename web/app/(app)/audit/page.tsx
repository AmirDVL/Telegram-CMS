"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { Paginated, PostEvent } from "@/lib/types";

export default function AuditPage() {
  const [items, setItems] = useState<PostEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<Paginated<PostEvent>>("/audit?limit=100")
      .then((d) => setItems(d.items))
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Audit log</h1>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      <div className="overflow-hidden rounded border border-slate-200 bg-white">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2">When</th>
              <th className="px-3 py-2">Post</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Actor</th>
              <th className="px-3 py-2">Payload</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.id} className="border-t border-slate-100">
                <td className="px-3 py-2 text-xs text-slate-500">{new Date(e.created_at).toLocaleString()}</td>
                <td className="px-3 py-2">#{e.post_id}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{e.action}</span>
                </td>
                <td className="px-3 py-2 text-xs">{e.actor_admin_id ?? "system"}</td>
                <td className="px-3 py-2">
                  <code className="text-xs text-slate-500">
                    {Object.keys(e.payload).length ? JSON.stringify(e.payload) : ""}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
