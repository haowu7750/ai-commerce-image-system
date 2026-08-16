"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { ROLE_POLICIES, type UserRole } from "@/lib/permissions";
import { useSession } from "@/lib/session";

export function AccessGate({
  requiredRole,
  children,
}: {
  requiredRole: UserRole;
  children: ReactNode;
}) {
  const { user, loading } = useSession();

  if (loading) {
    return (
      <main className="grid min-h-screen place-items-center">
        <p className="text-sm font-bold text-stone-500">正在验证登录状态…</p>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl items-center px-6">
        <section className="panel w-full p-8 text-center">
          <p className="eyebrow">需要登录</p>
          <h1 className="mt-3 text-2xl font-black">请先登录系统</h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">
            页面会调用后端验证令牌和角色，不再通过 URL 伪造演示身份。
          </p>
          <Link className="button-primary mt-6" href="/login">
            前往登录
          </Link>
        </section>
      </main>
    );
  }

  if (!user.roles.includes(requiredRole)) {
    const fallbackRole = user.roles[0];
    const home = fallbackRole ? ROLE_POLICIES[fallbackRole].home : "/login";
    return (
      <main className="mx-auto flex min-h-screen max-w-xl items-center px-6">
        <section className="panel w-full p-8 text-center">
          <p className="eyebrow">服务端角色边界</p>
          <h1 className="mt-3 text-2xl font-black">当前账号无权访问此工作区</h1>
          <p className="mt-3 text-sm leading-6 text-stone-600">
            需要 {ROLE_POLICIES[requiredRole].label} 角色。管理员身份不会自动获得运营确认权。
          </p>
          <Link className="button-primary mt-6" href={home}>
            返回我的工作区
          </Link>
        </section>
      </main>
    );
  }

  return <AppShell role={requiredRole}>{children}</AppShell>;
}
