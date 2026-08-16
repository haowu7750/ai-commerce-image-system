"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { ROLE_POLICIES, type UserRole } from "@/lib/permissions";
import { useSession } from "@/lib/session";

export function AppShell({
  role,
  children,
}: {
  role: UserRole;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useSession();
  const policy = ROLE_POLICIES[role];

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[270px_1fr]">
      <aside className="border-b border-black/5 bg-[#18362b] px-5 py-5 text-white lg:min-h-screen lg:border-b-0 lg:px-6 lg:py-8">
        <div className="flex items-center justify-between gap-4 lg:block">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-200">
              Commerce studio
            </p>
            <p className="mt-2 text-xl font-black">商策 AI 工作台</p>
          </div>
          <span className="rounded-full border border-emerald-200/30 bg-emerald-100/10 px-3 py-1 text-xs font-bold text-emerald-100">
            本地功能版
          </span>
        </div>

        <nav className="mt-7 grid gap-2 sm:grid-cols-3 lg:grid-cols-1" aria-label="主导航">
          {policy.nav.map((item) => (
            <Link
              className={
                pathname === item.href || pathname.startsWith(item.href + "/")
                  ? "rounded-xl bg-white px-3 py-2.5 text-sm font-bold text-[#18362b]"
                  : "rounded-xl px-3 py-2.5 text-sm font-semibold text-emerald-50/80 transition hover:bg-white/10 hover:text-white"
              }
              href={item.href}
              key={item.label}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="mt-7 rounded-2xl border border-white/10 bg-black/10 p-4 text-xs leading-5 text-emerald-50/75">
          <p className="font-bold text-white">{policy.label}权限</p>
          <p className="mt-1">{policy.summary}</p>
        </div>
      </aside>

      <main className="min-w-0">
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 bg-white/75 px-5 py-4 backdrop-blur md:px-8">
          <div>
            <p className="text-sm font-bold text-ink">
              {user?.display_name ?? policy.label}
            </p>
            <p className="text-xs text-stone-500">
              {user?.email} · {user?.roles.join(" / ")}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="status-chip">后端已连接</span>
            <button
              className="button-secondary !py-2"
              onClick={() => {
                logout();
                router.push("/login");
              }}
              type="button"
            >
              退出登录
            </button>
          </div>
        </header>
        <div className="px-5 py-7 md:px-8 lg:px-10 lg:py-9">{children}</div>
      </main>
    </div>
  );
}
