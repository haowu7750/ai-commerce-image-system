"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import {
  ApiError,
  apiRequest,
  type DesignTask,
  type Project,
} from "@/lib/api";

const statusLabels: Record<string, string> = {
  draft: "草稿",
  needs_information: "待补资料",
  in_progress: "处理中",
  waiting_for_design: "等待美工",
  waiting_for_operator_review: "待运营验收",
  ready_to_publish: "待上架",
  completed: "已完成",
  archived: "已归档",
};

export default function WorkspacePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [tasks, setTasks] = useState<DesignTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      apiRequest<Project[]>("/projects"),
      apiRequest<DesignTask[]>("/design-tasks"),
    ])
      .then(([projectRows, taskRows]) => {
        setProjects(projectRows);
        setTasks(taskRows);
      })
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "工作台加载失败"),
      )
      .finally(() => setLoading(false));
  }, []);

  const metrics = useMemo(
    () => [
      { label: "商品项目", value: projects.length, note: "数据库中的项目总数" },
      {
        label: "待验收设计",
        value: tasks.filter((task) => task.status === "submitted").length,
        note: "美工已提交，等待运营处理",
      },
      {
        label: "进行中任务",
        value: tasks.filter((task) =>
          ["assigned", "viewed", "in_progress", "rework"].includes(task.status),
        ).length,
        note: "已分配但尚未完成",
      },
    ],
    [projects, tasks],
  );

  return (
    <AccessGate requiredRole="operator">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">运营工作台</p>
          <h1 className="mt-2 text-3xl font-black">从真实项目推进业务任务</h1>
          <p className="mt-2 text-sm text-stone-600">
            指标来自后端数据库；创建、确认和任务操作刷新后仍会保留。
          </p>
        </div>
        <Link className="button-primary" href="/projects">
          新建商品项目
        </Link>
      </div>

      {error ? <p className="notice-error mt-5">{error}</p> : null}

      <section className="mt-7 grid gap-4 md:grid-cols-3" aria-label="运营指标">
        {metrics.map((metric) => (
          <article className="panel p-5" key={metric.label}>
            <p className="text-sm font-bold text-stone-500">{metric.label}</p>
            <p className="mt-2 text-3xl font-black">
              {loading ? "…" : metric.value}
            </p>
            <p className="mt-1 text-xs text-stone-400">{metric.note}</p>
          </article>
        ))}
      </section>

      <section className="panel mt-6 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-4">
          <div>
            <h2 className="font-black">最近项目</h2>
            <p className="mt-1 text-xs text-stone-500">
              按最近更新时间排序
            </p>
          </div>
          <Link className="text-sm font-bold text-brand-700" href="/projects">
            查看全部
          </Link>
        </div>
        {projects.length ? (
          <div className="divide-y divide-stone-100">
            {projects.slice(0, 5).map((project) => (
              <Link
                className="grid gap-3 px-5 py-4 transition hover:bg-stone-50 md:grid-cols-[1.4fr_0.6fr_0.8fr] md:items-center"
                href={`/projects/${project.id}`}
                key={project.id}
              >
                <div>
                  <p className="font-bold">{project.name}</p>
                  <p className="mt-1 text-xs text-stone-500">
                    {project.store_name} · {project.platform}
                  </p>
                </div>
                <span className="status-chip w-fit">
                  {statusLabels[project.status] ?? project.status}
                </span>
                <p className="text-sm font-bold text-brand-700">打开项目 →</p>
              </Link>
            ))}
          </div>
        ) : (
          <div className="px-5 py-12 text-center text-sm text-stone-500">
            尚无项目。创建第一个项目后，这里会显示真实数据。
          </div>
        )}
      </section>

      <section className="mt-6 grid gap-4 md:grid-cols-3">
        {[
          ["商品事实与素材", "维护商品卡、上传产品参考图并由运营确认。", "/projects"],
          ["AI 生图", "按七阶段推进 Mock 生图、检查与人工确认。", "/image-studio"],
          ["美工验收", "查看提交版本、确认通过或退回返工。", "/tasks"],
        ].map(([title, description, href]) => (
          <Link className="panel p-5 transition hover:-translate-y-0.5" href={href} key={title}>
            <h2 className="font-black">{title}</h2>
            <p className="mt-2 text-sm leading-6 text-stone-600">{description}</p>
          </Link>
        ))}
      </section>
    </AccessGate>
  );
}
