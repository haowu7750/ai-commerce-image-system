"use client";

import { useCallback, useEffect, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import { ApiError, apiRequest, jsonBody, type DesignTask } from "@/lib/api";

export default function OperatorTasksPage() {
  const [tasks, setTasks] = useState<DesignTask[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
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

  async function review(task: DesignTask, decision: "accepted" | "partial" | "rework") {
    const reviewNote =
      notes[task.id]?.trim() ||
      (decision === "accepted" ? "运营确认设计结果符合需求。" : "");
    if (reviewNote.length < 2) {
      setError("退回返工时必须填写具体原因。");
      return;
    }
    setBusy(task.id + decision);
    setError("");
    setMessage("");
    try {
      await apiRequest(`/design-tasks/${task.id}/review`, {
        method: "POST",
        ...jsonBody({ decision, notes: reviewNote }),
      });
      setMessage(
        decision === "accepted"
          ? "设计结果已确认通过。"
          : decision === "partial"
            ? "已记录部分通过，任务回到美工继续修改。"
            : "任务已退回返工。",
      );
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "验收失败");
    } finally {
      setBusy("");
    }
  }

  async function cancel(task: DesignTask) {
    const reason = notes[task.id]?.trim();
    if (!reason || reason.length < 2) {
      setError("取消任务前请在验收意见中填写原因。");
      return;
    }
    setBusy(task.id + "cancel");
    setError("");
    setMessage("");
    try {
      await apiRequest(`/design-tasks/${task.id}/cancel`, {
        method: "POST",
        ...jsonBody({ reason }),
      });
      setMessage("任务已取消并保留操作记录。");
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "取消失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <AccessGate requiredRole="operator">
      <p className="eyebrow">美工协作</p>
      <h1 className="mt-2 text-3xl font-black">任务分配与运营验收</h1>
      <p className="mt-2 text-sm text-stone-600">
        美工提交的每个版本都会保留；通过或返工决定由运营执行并进入审计。
      </p>

      {message ? <p className="notice-success mt-5">{message}</p> : null}
      {error ? <p className="notice-error mt-5">{error}</p> : null}

      <div className="mt-7 grid gap-5">
        {tasks.map((task) => (
          <article className="panel p-6" key={task.id}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-xs font-bold text-brand-700">
                  {task.project_name}
                </p>
                <h2 className="mt-1 text-xl font-black">{task.title}</h2>
                <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
                  {task.brief}
                </p>
              </div>
              <span className="status-chip">
                {task.status} · {task.assigned_to_name}
              </span>
            </div>

            {task.requirements.length ? (
              <ul className="mt-4 grid gap-2 md:grid-cols-2">
                {task.requirements.map((requirement, index) => (
                  <li className="rounded-xl bg-stone-50 p-3 text-sm" key={index}>
                    {String(requirement.item ?? JSON.stringify(requirement))}
                  </li>
                ))}
              </ul>
            ) : null}

            <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {task.submissions.map((submission) => (
                <article className="overflow-hidden rounded-2xl border border-stone-200" key={submission.id}>
                  {submission.file_url.startsWith("data:image") ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      alt={`设计提交 V${submission.version_no}`}
                      className="aspect-square w-full object-contain"
                      src={submission.file_url}
                    />
                  ) : (
                    <a
                      className="block p-4 font-bold text-brand-700"
                      href={submission.file_url}
                      rel="noreferrer"
                      target="_blank"
                    >
                      打开提交文件
                    </a>
                  )}
                  <div className="p-3">
                    <p className="font-bold">版本 V{submission.version_no}</p>
                    <p className="mt-1 text-xs text-stone-500">{submission.notes}</p>
                  </div>
                </article>
              ))}
            </div>

            {task.status === "submitted" ? (
              <div className="mt-5 rounded-2xl bg-stone-50 p-4">
                <label className="form-label">
                  验收意见
                  <textarea
                    className="form-input min-h-24"
                    onChange={(event) =>
                      setNotes((current) => ({
                        ...current,
                        [task.id]: event.target.value,
                      }))
                    }
                    placeholder="通过可填写确认说明；退回必须说明具体修改点。"
                    value={notes[task.id] ?? ""}
                  />
                </label>
                <div className="mt-3 flex flex-wrap gap-3">
                  <button
                    className="button-primary"
                    disabled={busy !== ""}
                    onClick={() => review(task, "accepted")}
                    type="button"
                  >
                    确认通过
                  </button>
                  <button
                    className="button-secondary"
                    disabled={busy !== ""}
                    onClick={() => review(task, "partial")}
                    type="button"
                  >
                    部分通过并继续修改
                  </button>
                  <button
                    className="button-secondary"
                    disabled={busy !== ""}
                    onClick={() => review(task, "rework")}
                    type="button"
                  >
                    退回返工
                  </button>
                </div>
              </div>
            ) : null}

            {!['completed', 'cancelled'].includes(task.status) ? (
              <div className="mt-4 flex justify-end">
                <button
                  className="text-sm font-bold text-red-700 underline underline-offset-4"
                  disabled={busy !== ""}
                  onClick={() => void cancel(task)}
                  type="button"
                >
                  取消任务（需填写原因）
                </button>
              </div>
            ) : null}

            {task.review_notes ? (
              <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                最近验收意见：{task.review_notes}
              </p>
            ) : null}
          </article>
        ))}
        {!tasks.length ? (
          <div className="panel p-10 text-center text-sm text-stone-500">
            暂无美工任务。请在商品项目详情中创建并分配任务。
          </div>
        ) : null}
      </div>
    </AccessGate>
  );
}
