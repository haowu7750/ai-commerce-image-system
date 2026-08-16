"use client";

import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import { AccessGate } from "@/components/access-gate";
import {
  ApiError,
  apiRequest,
  fileToDataUrl,
  jsonBody,
  type DesignTask,
} from "@/lib/api";

export default function DesignerPage() {
  const [tasks, setTasks] = useState<DesignTask[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      setTasks(await apiRequest<DesignTask[]>("/design-tasks"));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "任务加载失败");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function updateStatus(
    task: DesignTask,
    status: "viewed" | "in_progress" | "needs_information",
  ) {
    const note = notes[task.id]?.trim() || null;
    if (status === "needs_information" && !note) {
      setError("请求补充资料时必须填写具体问题。");
      return;
    }
    setBusy(task.id + status);
    setError("");
    setMessage("");
    try {
      await apiRequest(`/design-tasks/${task.id}/status`, {
        method: "PATCH",
        ...jsonBody({ status, note }),
      });
      setMessage("任务状态已更新并保存。");
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "状态更新失败");
    } finally {
      setBusy("");
    }
  }

  async function submit(task: DesignTask) {
    const file = files[task.id];
    if (!file) {
      setError("请选择要提交的设计文件。");
      return;
    }
    if (file.size > 1_200_000) {
      setError("本地功能版单个提交文件请控制在 1.2MB 以内。");
      return;
    }
    setBusy(task.id + "submit");
    setError("");
    setMessage("");
    try {
      await apiRequest(`/design-tasks/${task.id}/submissions`, {
        method: "POST",
        ...jsonBody({
          file_url: await fileToDataUrl(file),
          notes: notes[task.id] ?? "",
        }),
      });
      setMessage("新设计版本已提交，等待运营验收。");
      setFiles((current) => ({ ...current, [task.id]: null }));
      setNotes((current) => ({ ...current, [task.id]: "" }));
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "版本提交失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <AccessGate requiredRole="designer">
      <p className="eyebrow">美工端</p>
      <h1 className="mt-2 text-3xl font-black">我的设计任务</h1>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
        这里只返回分配给当前美工的任务。可以更新进度、请求补充信息并提交多版结果，但不能修改商品事实或确认最终上架版本。
      </p>

      {message ? <p className="notice-success mt-5">{message}</p> : null}
      {error ? <p className="notice-error mt-5">{error}</p> : null}

      <div className="mt-7 grid gap-5">
        {tasks.map((task) => (
          <article className="panel p-6" key={task.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold text-brand-700">
                  {task.project_name} · {task.product_name ?? "商品卡待补充"}
                </p>
                <h2 className="mt-1 text-xl font-black">{task.title}</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
                  {task.brief}
                </p>
              </div>
              <span className="status-chip">
                {task.status} · {task.priority}
              </span>
            </div>

            <section className="mt-5 rounded-2xl bg-stone-50 p-4">
              <h3 className="text-sm font-black">验收要求</h3>
              <ul className="mt-3 grid gap-2 md:grid-cols-2">
                {task.requirements.map((requirement, index) => (
                  <li className="rounded-xl bg-white p-3 text-sm" key={index}>
                    {String(requirement.item ?? JSON.stringify(requirement))}
                  </li>
                ))}
                {!task.requirements.length ? (
                  <li className="text-sm text-stone-500">按任务说明执行。</li>
                ) : null}
              </ul>
            </section>

            <div className="mt-5 flex flex-wrap gap-3">
              {task.status === "assigned" ? (
                <button
                  className="button-secondary"
                  disabled={busy !== ""}
                  onClick={() => updateStatus(task, "viewed")}
                  type="button"
                >
                  标记已查看
                </button>
              ) : null}
              {["assigned", "viewed", "rework", "needs_information"].includes(
                task.status,
              ) ? (
                <button
                  className="button-primary"
                  disabled={busy !== ""}
                  onClick={() => updateStatus(task, "in_progress")}
                  type="button"
                >
                  开始/继续处理
                </button>
              ) : null}
            </div>

            {!["completed", "submitted", "cancelled"].includes(task.status) ? (
              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <label className="form-label">
                  问题或版本说明
                  <textarea
                    className="form-input min-h-28"
                    onChange={(event) =>
                      setNotes((current) => ({
                        ...current,
                        [task.id]: event.target.value,
                      }))
                    }
                    placeholder="请求补充时填写问题；提交时填写修改说明。"
                    value={notes[task.id] ?? ""}
                  />
                </label>
                <div className="grid content-start gap-3">
                  <button
                    className="button-secondary"
                    disabled={busy !== ""}
                    onClick={() => updateStatus(task, "needs_information")}
                    type="button"
                  >
                    请求运营补充资料
                  </button>
                  <label className="button-secondary cursor-pointer">
                    选择设计文件
                    <input
                      accept="image/*"
                      className="hidden"
                      onChange={(event: ChangeEvent<HTMLInputElement>) =>
                        setFiles((current) => ({
                          ...current,
                          [task.id]: event.target.files?.[0] ?? null,
                        }))
                      }
                      type="file"
                    />
                  </label>
                  <p className="text-xs text-stone-500">
                    {files[task.id]?.name ?? "尚未选择文件"}
                  </p>
                  <button
                    className="button-primary"
                    disabled={busy !== "" || !files[task.id]}
                    onClick={() => submit(task)}
                    type="button"
                  >
                    提交新版本
                  </button>
                </div>
              </div>
            ) : null}

            {task.review_notes ? (
              <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                运营验收意见：{task.review_notes}
              </p>
            ) : null}

            {task.submissions.length ? (
              <div className="mt-5 flex flex-wrap gap-2">
                {task.submissions.map((submission) => (
                  <span className="status-chip" key={submission.id}>
                    已提交 V{submission.version_no}
                  </span>
                ))}
              </div>
            ) : null}
          </article>
        ))}

        {!tasks.length ? (
          <div className="panel p-10 text-center text-sm text-stone-500">
            当前没有分配给你的任务。
          </div>
        ) : null}
      </div>
    </AccessGate>
  );
}
