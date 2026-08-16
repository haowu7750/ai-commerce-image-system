"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError, type User, type UserRole } from "@/lib/api";
import { ROLE_POLICIES, roleKeys } from "@/lib/permissions";
import { useSession } from "@/lib/session";

const roleMeta: Record<UserRole, { marker: string; detail: string }> = {
  operator: {
    marker: "运",
    detail: "创建商品项目、确认内容、发起生图并验收美工结果。",
  },
  designer: {
    marker: "美",
    detail: "接收任务、更新进度并提交多版设计结果。",
  },
  admin: {
    marker: "管",
    detail: "管理用户角色、Prompt、规则、连接配置和审计。",
  },
};

function homeForUser(user: User) {
  const priority: UserRole[] = ["operator", "designer", "admin"];
  const role = priority.find((candidate) => user.roles.includes(candidate));
  return role ? ROLE_POLICIES[role].home : "/login";
}

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, login, demoLogin } = useSession();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loading && user) {
      router.replace(homeForUser(user));
    }
  }, [loading, router, user]);

  async function run(action: () => Promise<User>, key: string) {
    setSubmitting(key);
    setError("");
    try {
      const nextUser = await action();
      router.push(homeForUser(nextUser));
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "登录失败，请确认后端已启动。",
      );
    } finally {
      setSubmitting(null);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await run(() => login(identifier, password), "password");
  }

  return (
    <main className="mx-auto min-h-screen max-w-7xl px-5 py-8 md:px-8 lg:grid lg:grid-cols-[0.9fr_1.1fr] lg:items-center lg:gap-16 lg:py-16">
      <section className="py-8 lg:py-0">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[#18362b] text-lg font-black text-white">
            商
          </span>
          <div>
            <p className="font-black">商策 AI 工作台</p>
            <p className="text-xs text-stone-500">本地功能开发版</p>
          </div>
        </div>

        <p className="eyebrow mt-16">Role-based commerce workflow</p>
        <h1 className="mt-4 max-w-2xl text-4xl font-black leading-tight tracking-tight md:text-5xl">
          三个角色，各自完成
          <br />
          可以保存的真实任务。
        </h1>
        <p className="mt-6 max-w-xl text-base leading-7 text-stone-600">
          登录会请求后端、签发令牌并校验角色。项目、商品卡、美工任务、配置和审计均写入本地数据库。
        </p>
      </section>

      <section className="panel p-5 md:p-7" aria-labelledby="login-heading">
        <div>
          <p className="eyebrow">快速进入</p>
          <h2 className="mt-2 text-2xl font-black" id="login-heading">
            选择本地演示角色
          </h2>
          <p className="mt-2 text-sm text-stone-600">
            演示登录只在非生产环境开放，但使用真实后端令牌和权限校验。
          </p>
        </div>

        <div className="mt-5 grid gap-3">
          {roleKeys.map((role) => {
            const policy = ROLE_POLICIES[role];
            const meta = roleMeta[role];
            return (
              <button
                className="group flex items-center gap-4 rounded-2xl border border-stone-200 bg-white p-4 text-left transition hover:-translate-y-0.5 hover:border-brand-500 hover:shadow-md disabled:opacity-50"
                disabled={submitting !== null}
                key={role}
                onClick={() => run(() => demoLogin(role), role)}
                type="button"
              >
                <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-50 font-black text-brand-700">
                  {meta.marker}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="font-black">{policy.label}</span>
                  <span className="mt-1 block text-sm text-stone-600">
                    {meta.detail}
                  </span>
                </span>
                <span className="text-sm font-bold text-brand-700">
                  {submitting === role ? "登录中…" : "进入"}
                </span>
              </button>
            );
          })}
        </div>

        <div className="my-6 flex items-center gap-3 text-xs text-stone-400">
          <span className="h-px flex-1 bg-stone-200" />
          已创建账号可使用密码登录
          <span className="h-px flex-1 bg-stone-200" />
        </div>

        <form className="grid gap-3" onSubmit={submit}>
          <label className="grid gap-1 text-sm font-bold">
            邮箱
            <input
              className="form-input"
              onChange={(event) => setIdentifier(event.target.value)}
              placeholder="name@example.com"
              required
              type="email"
              value={identifier}
            />
          </label>
          <label className="grid gap-1 text-sm font-bold">
            密码
            <input
              className="form-input"
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          <button
            className="button-secondary mt-1"
            disabled={submitting !== null}
            type="submit"
          >
            {submitting === "password" ? "正在登录…" : "账号密码登录"}
          </button>
        </form>

        {error ? (
          <p className="mt-4 rounded-xl bg-red-50 px-4 py-3 text-sm font-bold text-red-700">
            {error}
          </p>
        ) : null}
      </section>
    </main>
  );
}
