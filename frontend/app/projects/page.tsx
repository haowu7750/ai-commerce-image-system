"use client";

import Link from "next/link";
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AccessGate } from "@/components/access-gate";
import { ApiError, apiRequest, jsonBody, type Project } from "@/lib/api";

type Bucket = "draft" | "in_progress" | "completed" | "deleted";
type ProjectFilters = {
  q: string;
  platform: string;
  store_name: string;
  category: string;
};

const emptyFilters: ProjectFilters = {
  q: "",
  platform: "",
  store_name: "",
  category: "",
};

const buckets: Array<{ key: Bucket; label: string; empty: string }> = [
  { key: "draft", label: "草稿箱", empty: "草稿箱为空，可新建一个项目。" },
  { key: "in_progress", label: "进行中", empty: "暂无进行中的项目。" },
  { key: "completed", label: "已完成", empty: "暂无已完成项目。" },
  { key: "deleted", label: "已删除", empty: "暂无已删除项目。" },
];

const statusLabels: Record<string, string> = {
  draft: "草稿",
  needs_information: "待补资料",
  in_progress: "进行中",
  waiting_for_design: "等待美工",
  waiting_for_operator_review: "待运营验收",
  ready_to_publish: "待上架",
  completed: "已完成",
  archived: "已删除",
};

export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [bucket, setBucket] = useState<Bucket>("draft");
  const [showCreate, setShowCreate] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [filters, setFilters] = useState<ProjectFilters>(emptyFilters);

  const load = useCallback(async () => {
    try {
      const query = new URLSearchParams({ bucket });
      Object.entries(filters).forEach(([key, value]) => {
        if (value.trim()) query.set(key, value.trim());
      });
      setProjects(await apiRequest<Project[]>(`/projects?${query.toString()}`));
      setError("");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "项目加载失败");
    }
  }, [bucket, filters]);

  useEffect(() => { void load(); }, [load]);

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      await apiRequest<Project>("/projects", {
        method: "POST",
        ...jsonBody({
          name: String(data.get("name") ?? ""),
          platform: String(data.get("platform") ?? "拼多多"),
          store_name: String(data.get("store_name") ?? ""),
          category: String(data.get("category") ?? "") || null,
        }),
      });
      form.reset();
      setShowCreate(false);
      setMessage("项目已保存到草稿箱。完善资料后可点击“开始项目”。");
      if (bucket === "draft") await load(); else setBucket("draft");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "项目创建失败");
    } finally {
      setSubmitting(false);
    }
  }

  async function runAction(project: Project, endpoint: string, success: string) {
    setActionId(project.id);
    setError("");
    setMessage("");
    try {
      await apiRequest<Project>(`/projects/${project.id}/${endpoint}`, { method: "POST" });
      setMessage(success);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "项目操作失败");
    } finally {
      setActionId(null);
    }
  }

  async function deleteProject(project: Project) {
    const reason = window.prompt(
      `请输入删除“${project.name}”的原因（至少 2 个字符）：`,
    )?.trim();
    if (!reason) return;
    if (reason.length < 2) {
      setError("删除原因至少需要 2 个字符。");
      return;
    }
    if (!window.confirm("确定删除该项目吗？项目会进入“已删除”，历史数据不会被物理清除。")) return;
    setActionId(project.id);
    setError("");
    setMessage("");
    try {
      await apiRequest<Project>(`/projects/${project.id}/delete`, {
        method: "POST",
        ...jsonBody({ reason }),
      });
      setMessage("项目已移入“已删除”，可由运营或管理员恢复。");
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "项目删除失败");
    } finally {
      setActionId(null);
    }
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setFilters({
      q: String(data.get("q") ?? ""),
      platform: String(data.get("platform") ?? ""),
      store_name: String(data.get("store_name") ?? ""),
      category: String(data.get("category") ?? ""),
    });
  }

  return (
    <AccessGate requiredRole="operator">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">运营 · 项目中心</p>
          <h1 className="mt-2 text-3xl font-black">草稿、执行与完成</h1>
          <p className="mt-2 text-sm text-stone-600">新建项目先进入草稿箱；开始后进入进行中；满足交付门禁后由运营标记完成。</p>
        </div>
        <button className="button-primary" onClick={() => setShowCreate((value) => !value)} type="button">{showCreate ? "收起表单" : "新建项目"}</button>
      </div>

      {showCreate && (
        <form className="panel mt-6 grid gap-4 p-6 md:grid-cols-2" onSubmit={createProject}>
          <label className="form-label">项目名称<input className="form-input" name="name" required /></label>
          <label className="form-label">店铺名称<input className="form-input" name="store_name" required /></label>
          <label className="form-label">平台<select className="form-input" defaultValue="拼多多" name="platform"><option>拼多多</option><option>淘宝</option><option>抖音电商</option><option>Amazon</option><option>Etsy</option></select></label>
          <label className="form-label">类目<input className="form-input" name="category" placeholder="例如：家居收纳" /></label>
          <div className="md:col-span-2"><button className="button-primary" disabled={submitting} type="submit">{submitting ? "正在保存…" : "保存到草稿箱"}</button></div>
        </form>
      )}

      {error && <p className="notice-error mt-5">{error}</p>}
      {message && <p className="notice-success mt-5">{message}</p>}

      <form className="panel mt-6 grid gap-3 p-4 md:grid-cols-[1.4fr_1fr_1fr_1fr_auto_auto]" onSubmit={applyFilters}>
        <label className="form-label">
          搜索
          <input className="form-input" defaultValue={filters.q} name="q" placeholder="项目、店铺或类目" />
        </label>
        <label className="form-label">
          平台
          <select className="form-input" defaultValue={filters.platform} name="platform">
            <option value="">全部平台</option>
            <option>拼多多</option>
            <option>淘宝</option>
            <option>抖音电商</option>
            <option>Amazon</option>
            <option>Etsy</option>
          </select>
        </label>
        <label className="form-label">
          店铺
          <input className="form-input" defaultValue={filters.store_name} name="store_name" placeholder="模糊匹配" />
        </label>
        <label className="form-label">
          类目
          <input className="form-input" defaultValue={filters.category} name="category" placeholder="模糊匹配" />
        </label>
        <button className="button-primary self-end" type="submit">筛选</button>
        <button
          className="button-secondary self-end"
          onClick={(event) => {
            event.currentTarget.form?.reset();
            setFilters(emptyFilters);
          }}
          type="button"
        >
          清空
        </button>
      </form>

      <div className="mt-6 flex flex-wrap gap-2" role="tablist" aria-label="项目阶段">
        {buckets.map((item) => <button aria-selected={bucket === item.key} className={bucket === item.key ? "button-primary" : "button-secondary"} key={item.key} onClick={() => { setBucket(item.key); setMessage(""); }} role="tab" type="button">{item.label}</button>)}
      </div>

      <div className="panel mt-7 overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-stone-100 bg-stone-50/70 text-xs uppercase tracking-wider text-stone-500"><tr><th className="px-5 py-4">项目</th><th className="px-5 py-4">平台/店铺</th><th className="px-5 py-4">类目</th><th className="px-5 py-4">状态</th><th className="px-5 py-4">操作</th></tr></thead>
          <tbody className="divide-y divide-stone-100">
            {projects.map((project) => (
              <tr key={project.id}>
                <td className="px-5 py-4"><p className="font-bold">{project.name}</p><p className="mt-1 text-xs text-stone-400">{bucket === "deleted" && project.archived_at ? `删除于 ${new Date(project.archived_at).toLocaleString("zh-CN")}` : `更新于 ${new Date(project.updated_at).toLocaleString("zh-CN")}`}</p>{bucket === "deleted" && project.deletion_reason && <p className="mt-1 max-w-sm text-xs text-red-700">原因：{project.deletion_reason}</p>}</td>
                <td className="px-5 py-4">{project.platform} · {project.store_name}</td>
                <td className="px-5 py-4">{project.category ?? "未填写"}</td>
                <td className="px-5 py-4"><span className="status-chip">{statusLabels[project.status] ?? project.status}</span>{bucket === "deleted" && project.status_before_delete && <p className="mt-2 text-xs text-stone-500">删除前：{statusLabels[project.status_before_delete] ?? project.status_before_delete}</p>}</td>
                <td className="px-5 py-4"><div className="flex flex-wrap items-center gap-4">
                  {bucket !== "deleted" && <Link className="font-bold text-brand-700 hover:underline" href={`/projects/${project.id}`}>{bucket === "completed" ? "查看" : "进入项目"}</Link>}
                  {bucket === "draft" && <button className="font-bold text-brand-700 hover:underline disabled:text-stone-300" disabled={actionId === project.id} onClick={() => void runAction(project, "start", "项目已开始，进入进行中。") } type="button">开始项目</button>}
                  {bucket === "in_progress" && <button className="font-bold text-brand-700 hover:underline disabled:text-stone-300" disabled={actionId === project.id} onClick={() => void runAction(project, "complete", "项目已完成。") } type="button">标记完成</button>}
                  {bucket === "completed" && <button className="font-bold text-brand-700 hover:underline disabled:text-stone-300" disabled={actionId === project.id} onClick={() => void runAction(project, "reopen", "项目已重新开启，回到进行中。") } type="button">重新开启</button>}
                  {bucket !== "deleted" && <button className="font-bold text-red-600 hover:underline disabled:text-stone-300" disabled={actionId === project.id} onClick={() => void deleteProject(project)} type="button">删除</button>}
                  {bucket === "deleted" && <button className="font-bold text-brand-700 hover:underline disabled:text-stone-300" disabled={actionId === project.id} onClick={() => void runAction(project, "restore", "项目已恢复到删除前状态。") } type="button">恢复项目</button>}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!projects.length && <div className="px-5 py-12 text-center text-sm text-stone-500">{buckets.find((item) => item.key === bucket)?.empty}</div>}
      </div>
    </AccessGate>
  );
}
