"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useEffect, useState } from "react";
import { fetchMeta } from "@/lib/api";

const LINKS = [
  { href: "/queue", label: "Queue" },
  { href: "/sources", label: "Sources" },
  { href: "/templates", label: "Templates" },
  { href: "/tags", label: "Tags" },
  { href: "/admins", label: "Admins" },
  { href: "/audit", label: "Audit" },
];

export function Nav() {
  const pathname = usePathname();
  const { admin, logout } = useAuth();
  const [showTenants, setShowTenants] = useState(false);

  useEffect(() => {
    if (admin?.role === "super_admin") {
      fetchMeta()
        .then((meta) => setShowTenants(meta.multi_tenancy_enabled))
        .catch(() => {});
    }
  }, [admin]);

  return (
    <nav className="flex items-center gap-1 border-b border-slate-200 bg-white px-4 py-2">
      <span className="mr-4 font-bold text-slate-800">TG CMS</span>
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className={`rounded px-3 py-1 text-sm ${
            pathname === l.href
              ? "bg-slate-800 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          {l.label}
        </Link>
      ))}
      {showTenants && (
        <Link
          href="/tenants"
          className={`rounded px-3 py-1 text-sm ${
            pathname === "/tenants"
              ? "bg-slate-800 text-white"
              : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          Tenants
        </Link>
      )}
      <div className="ml-auto flex items-center gap-3 text-sm text-slate-500">
        {admin && (
          <span>
            {admin.username} <span className="text-xs">({admin.role})</span>
          </span>
        )}
        <button
          onClick={logout}
          className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100"
        >
          Logout
        </button>
      </div>
    </nav>
  );
}
