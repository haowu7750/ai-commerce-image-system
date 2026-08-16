"use client";

import { useCallback, useEffect, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import {
  apiRequest,
  type AuditEvent,
  type Project,
  type SystemResource,
  type User,
  type UserRole,
} from "@/lib/api";

const roleLabels: Record<UserRole, string> = {
  operator: "运营",
  designer: "设计",
  admin: "管理员",
};

export default function AdminPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [resources, setResources] = useState<SystemResource[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [deletedProjects, setDeletedProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [nextUsers, nextResources, nextEvents, nextDeletedProjects] = await Promise.all([
        apiRequest<User[]>("/admin/users"),
        apiRequest<SystemResource[]>("/admin/resources"),
        apiRequest<AuditEvent[]>("/admin/audit-events?limit=40"),
        apiRequest<Project[]>("/admin/deleted-projects"),
      ]);
      setUsers(nextUsers);
      setResources(nextResources);
      setEvents(nextEvents);
      setDeletedProjects(nextDeletedProjects);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "管理员数据加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function createUser(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const roles = data.getAll("roles") as UserRole[];
    setBusy(true);
    setError("");
    try {
      await apiRequest<User>("/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email: data.get("email"),
          display_name: data.get("display_name"),
          password: data.get("password"),
          roles,
        }),
      });
      form.reset();
      setMessage("用户已创建，角色权限立即生效。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "用户创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleUser(user: User) {
    setBusy(true);
    setError("");
    try {
      await apiRequest<User>(`/admin/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !user.is_active }),
      });
      setMessage(user.is_active ? "账号已停用。" : "账号已启用。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号状态更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function createResource(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    let content: Record<string, unknown>;
    try {
      content = JSON.parse(String(data.get("content"))) as Record<string, unknown>;
    } catch {
      setError("配置内容必须是合法 JSON。请勿在这里保存 API Key 或密码。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await apiRequest<SystemResource>("/admin/resources", {
        method: "POST",
        body: JSON.stringify({
          kind: data.get("kind"),
          name: data.get("name"),
          description: data.get("description"),
          content,
          is_active: true,
        }),
      });
      form.reset();
      setMessage("配置资源已保存并生成版本 1。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "配置保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function toggleResource(resource: SystemResource) {
    setBusy(true);
    setError("");
    try {
      await apiRequest<SystemResource>(`/admin/resources/${resource.id}`, {
        method: "PUT",
        body: JSON.stringify({ is_active: !resource.is_active }),
      });
      setMessage("配置状态已更新，并保留新的版本号。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "配置更新失败");
    } finally {
      setBusy(false);
    }
  }

  async function restoreDeletedProject(project: Project) {
    if (!window.confirm(`确定恢复“${project.name}”吗？项目将回到删除前的业务状态。`)) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest<Project>(`/admin/deleted-projects/${project.id}/restore`, {
        method: "POST",
      });
      setMessage("项目已由管理员恢复；该操作已写入审计，未执行任何业务确认。");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目恢复失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AccessGate requiredRole="admin">
      <p className="eyebrow">管理员中心 · 服务端权限</p>
      <h1 className="mt-2 text-3xl font-black">用户、规则与审计</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
        管理员负责账号、角色和系统资源，不自动拥有运营的商品确认或成果定稿权限。
      </p>

      {error && <p className="notice-error mt-5">{error}</p>}
      {message && <p className="notice-success mt-5">{message}</p>}

      <section className="mt-7 grid gap-6 xl:grid-cols-2">
        <article className="panel p-6">
          <h2 className="text-xl font-black">创建用户</h2>
          <form className="mt-5 grid gap-4" onSubmit={createUser}>
            <label className="form-label">姓名<input className="form-input" name="display_name" required /></label>
            <label className="form-label">邮箱<input className="form-input" name="email" required type="email" /></label>
            <label className="form-label">初始密码<input className="form-input" minLength={8} name="password" required type="password" /></label>
            <fieldset>
              <legend className="text-sm font-bold text-stone-700">角色</legend>
              <div className="mt-2 flex flex-wrap gap-4">
                {(Object.keys(roleLabels) as UserRole[]).map((role) => (
                  <label className="flex items-center gap-2 text-sm" key={role}>
                    <input defaultChecked={role === "designer"} name="roles" type="checkbox" value={role} />
                    {roleLabels[role]}
                  </label>
                ))}
              </div>
            </fieldset>
            <button className="button-primary" disabled={busy} type="submit">创建账号</button>
          </form>
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">账号与角色</h2>
          <div className="mt-4 grid gap-3">
            {users.map((user) => (
              <div className="rounded-2xl border border-stone-200 p-4" key={user.id}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-black">{user.display_name}</p>
                    <p className="mt-1 text-xs text-stone-500">{user.email}</p>
                    <div className="mt-2 flex gap-2">
                      {user.roles.map((role) => <span className="status-chip" key={role}>{roleLabels[role]}</span>)}
                    </div>
                  </div>
                  <button className="button-secondary" disabled={busy} onClick={() => void toggleUser(user)} type="button">
                    {user.is_active ? "停用" : "启用"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel mt-6 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h2 className="text-xl font-black">已删除项目</h2><p className="mt-2 text-sm text-stone-600">管理员可查看和执行数据恢复，但不能编辑项目内容或替代运营完成业务确认。</p></div>
          <span className="status-chip">{deletedProjects.length} 个</span>
        </div>
        <div className="mt-4 grid gap-3">
          {deletedProjects.length === 0 && <p className="text-sm text-stone-500">当前没有已删除项目。</p>}
          {deletedProjects.map((project) => {
            const owner = users.find((user) => user.id === project.created_by_id);
            return <article className="rounded-2xl border border-stone-200 p-4" key={project.id}>
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div><p className="font-black">{project.name}</p><p className="mt-1 text-xs text-stone-500">所属运营：{owner?.display_name ?? project.created_by_id} · 删除时间：{project.archived_at ? new Date(project.archived_at).toLocaleString("zh-CN") : "未知"}</p><p className="mt-2 text-sm text-red-700">删除原因：{project.deletion_reason ?? "旧记录未填写原因"}</p><p className="mt-1 text-xs text-stone-500">删除前状态：{project.status_before_delete ?? "draft"}</p></div>
                <button className="button-secondary" disabled={busy} onClick={() => void restoreDeletedProject(project)} type="button">恢复项目</button>
              </div>
            </article>;
          })}
        </div>
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-2">
        <article className="panel p-6">
          <h2 className="text-xl font-black">新增系统资源</h2>
          <p className="mt-2 text-xs leading-5 text-amber-800">只保存非敏感规则和连接元数据。API Key、密码应放在服务端环境变量中。</p>
          <form className="mt-5 grid gap-4" onSubmit={createResource}>
            <label className="form-label">类型
              <select className="form-input" name="kind"><option value="prompt">Prompt 模板</option><option value="compliance_rule">合规规则</option><option value="erp_connection">ERP 连接元数据</option></select>
            </label>
            <label className="form-label">名称<input className="form-input" name="name" required /></label>
            <label className="form-label">说明<textarea className="form-input" name="description" rows={2} /></label>
            <label className="form-label">内容（JSON）<textarea className="form-input font-mono" defaultValue={'{"template":"请根据已确认商品事实生成内容"}'} name="content" required rows={5} /></label>
            <button className="button-primary" disabled={busy} type="submit">保存配置</button>
          </form>
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">配置版本</h2>
          <div className="mt-4 grid gap-3">
            {resources.length === 0 && <p className="text-sm text-stone-500">暂无配置。</p>}
            {resources.map((resource) => (
              <div className="rounded-2xl border border-stone-200 p-4" key={resource.id}>
                <div className="flex items-start justify-between gap-3">
                  <div><p className="font-black">{resource.name}</p><p className="mt-1 text-xs text-stone-500">{resource.kind} · v{resource.version} · {resource.is_active ? "启用" : "停用"}</p></div>
                  <button className="button-secondary" disabled={busy} onClick={() => void toggleResource(resource)} type="button">{resource.is_active ? "停用" : "启用"}</button>
                </div>
                <pre className="mt-3 overflow-auto rounded-xl bg-stone-50 p-3 text-xs">{JSON.stringify(resource.content, null, 2)}</pre>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="panel mt-6 p-6">
        <h2 className="text-xl font-black">最近审计记录</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead><tr className="border-b text-xs text-stone-500"><th className="p-3">时间</th><th>动作</th><th>对象</th><th>结果</th><th>摘要</th></tr></thead>
            <tbody>{events.map((event) => <tr className="border-b border-stone-100" key={event.id}><td className="p-3 text-xs">{new Date(event.created_at).toLocaleString()}</td><td>{event.action}</td><td>{event.object_type}</td><td>{event.result}</td><td className="max-w-xs truncate text-xs">{JSON.stringify(event.payload_summary)}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </AccessGate>
  );
}
