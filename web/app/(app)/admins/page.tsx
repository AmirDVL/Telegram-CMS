"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Admin, Role } from "@/lib/types";

export default function AdminsPage() {
  const { admin: me } = useAuth();
  const [items, setItems] = useState<Admin[]>([]);
  const [error, setError] = useState<string | null>(null);
  const canManage = me?.role === "super_admin";

  const refresh = () =>
    apiFetch<Admin[]>("/admins")
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed"));

  useEffect(() => {
    refresh();
  }, []);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("editor");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    await apiFetch("/admins", { method: "POST", body: JSON.stringify({ username, password, role }) });
    setUsername("");
    setPassword("");
    refresh();
  };

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Admins</h1>
      {error && <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>}
      {canManage && (
        <form onSubmit={submit} className="flex flex-wrap gap-2 rounded border border-slate-200 bg-white p-3 text-sm">
          <input className="rounded border border-slate-300 px-2 py-1" placeholder="username" value={username} onChange={(e) => setUsername(e.target.value)} required />
          <input type="password" className="rounded border border-slate-300 px-2 py-1" placeholder="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <select className="rounded border border-slate-300 px-2 py-1" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="editor">editor</option>
            <option value="admin">admin</option>
            <option value="super_admin">super_admin</option>
          </select>
          <button className="rounded bg-slate-800 px-3 py-1 text-white hover:bg-slate-700">Add admin</button>
        </form>
      )}
      <div className="grid gap-2">
        {items.map((a) => (
          <div key={a.id} className="flex items-center justify-between rounded border border-slate-200 bg-white p-3 text-sm">
            <div>
              <span className="font-medium">{a.username}</span>{" "}
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs">{a.role}</span>
              {a.disabled_at && <span className="ml-2 text-xs text-red-600">disabled</span>}
            </div>
            {canManage && !a.disabled_at && (
              <button
                onClick={() =>
                  apiFetch(`/admins/${a.id}`, { method: "PATCH", body: JSON.stringify({ disabled: true }) }).then(refresh)
                }
                className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
              >
                Disable
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
