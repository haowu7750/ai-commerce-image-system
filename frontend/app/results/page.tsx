"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import { apiRequest, type Project } from "@/lib/api";

type TimelineEvent = {
  id: string;
  action: string;
  object_type: string;
  object_id: string | null;
  summary: Record<string, unknown>;
  result: string;
  created_at: string;
};

type DeliveryPackage = {
  project: {
    id: string;
    name: string;
    platform: string;
    store_name: string;
    status: string;
  };
  product_card: Record<string, unknown> | null;
  final_content: Record<string, Record<string, unknown>>;
  accepted_designs: Array<{
    task_id: string;
    task_title: string;
    version_no: number;
    file_url: string;
    notes: string;
  }>;
  confirmed_images: Array<{
    output_id: string;
    provider: string;
    model: string;
    provider_url: string | null;
    preview_data_url: string | null;
    revised_prompt: string | null;
  }>;
  blockers: string[];
  timeline: TimelineEvent[];
};

type TextExport = { filename: string; mime_type: string; content: string };

const ACTION_LABELS: Record<string, string> = {
  "project.created": "新建项目",
  "project.started": "项目进入执行",
  "product_card.updated": "更新商品信息卡",
  "product_card.confirmed": "运营确认商品事实",
  "content_version.created": "创建内容版本",
  "content_version.finalized": "运营确认最终内容",
  "image_generation.succeeded": "生图完成",
  "image_workflow.operator_confirmed": "运营确认生图结果",
  "design_task.created": "创建美工任务",
  "design_submission.created": "美工提交结果",
  "design_task.reviewed": "运营验收设计",
};

function download(filename: string, mimeType: string, content: string) {
  const blob = new Blob([content], { type: mimeType });
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export default function ResultsPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [result, setResult] = useState<DeliveryPackage | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [caseName, setCaseName] = useState("");

  const loadProjects = useCallback(async () => {
    try {
      const data = await apiRequest<Project[]>("/projects");
      setProjects(data);
      if (data[0]) setSelectedId((current) => current || data[0].id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "项目加载失败");
    }
  }, []);

  const loadResult = useCallback(async (projectId: string) => {
    if (!projectId) return;
    try {
      const data = await apiRequest<DeliveryPackage>(`/reports/projects/${projectId}`);
      setResult(data);
      setCaseName(`${data.project.name}-典型案例`);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "成果加载失败");
    }
  }, []);

  useEffect(() => { void loadProjects(); }, [loadProjects]);
  useEffect(() => {
    setResult(null);
    setNotice("");
    void loadResult(selectedId);
  }, [loadResult, selectedId]);

  async function exportText(kind: "markdown" | "sku-csv") {
    if (!selectedId) return;
    setBusy(kind);
    setError("");
    try {
      const payload = await apiRequest<TextExport>(
        `/reports/projects/${selectedId}/exports/${kind}`,
      );
      download(payload.filename, payload.mime_type, payload.content);
      setNotice(`${payload.filename} 已下载到浏览器下载目录。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导出失败");
    } finally {
      setBusy("");
    }
  }

  async function saveKnowledgeCase() {
    if (!selectedId || !caseName.trim()) return;
    setBusy("case");
    setError("");
    try {
      await apiRequest(`/reports/projects/${selectedId}/knowledge-case`, {
        method: "POST",
        body: JSON.stringify({ name: caseName.trim(), notes: "由运营成果中心人工沉淀" }),
      });
      setNotice("典型案例已保存，管理员可继续维护，运营可在内容工作台复用。 ");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "案例保存失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <AccessGate requiredRole="operator">
      <p className="eyebrow">运营成果中心</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black">最终成果、导出与操作时间线</h1>
          <p className="mt-2 text-sm text-stone-600">
            只汇总运营已确认的事实、内容、生图和设计结果；导出不会自动发布或写回 ERP。
          </p>
        </div>
        <label className="form-label min-w-64">
          项目
          <select
            className="form-input"
            onChange={(event) => setSelectedId(event.target.value)}
            value={selectedId}
          >
            <option value="">选择项目</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="notice-error mt-5">{error}</p>}
      {notice && <p className="notice-success mt-5">{notice}</p>}
      {!result && !error && (
        <section className="panel mt-6 p-8 text-sm text-stone-500">正在读取服务端成果…</section>
      )}

      {result && (
        <>
          <section className="mt-6 grid gap-4 md:grid-cols-4">
            <article className="panel p-5">
              <p className="text-xs text-stone-500">商品事实</p>
              <p className="mt-2 text-2xl font-black">{result.product_card ? "已保存" : "未保存"}</p>
            </article>
            <article className="panel p-5">
              <p className="text-xs text-stone-500">定稿内容</p>
              <p className="mt-2 text-2xl font-black">{Object.keys(result.final_content).length}</p>
            </article>
            <article className="panel p-5">
              <p className="text-xs text-stone-500">确认生图</p>
              <p className="mt-2 text-2xl font-black">{result.confirmed_images.length}</p>
            </article>
            <article className="panel p-5">
              <p className="text-xs text-stone-500">验收设计</p>
              <p className="mt-2 text-2xl font-black">{result.accepted_designs.length}</p>
            </article>
          </section>

          <section className="mt-6 grid gap-6 xl:grid-cols-[1fr_1.35fr]">
            <article className="panel p-6">
              <h2 className="text-xl font-black">交付门禁与导出</h2>
              {result.blockers.length === 0 ? (
                <p className="notice-success mt-4">关键门禁已通过，可以导出并沉淀为案例。</p>
              ) : (
                <ul className="mt-4 grid gap-2">
                  {result.blockers.map((blocker) => (
                    <li className="rounded-xl bg-amber-50 px-4 py-3 text-sm font-bold text-amber-900" key={blocker}>
                      {blocker}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-5 flex flex-wrap gap-3">
                <Link className="button-secondary" href={`/projects/${result.project.id}`}>返回项目补充</Link>
                <button
                  className="button-primary"
                  onClick={() => download(
                    `${result.project.name}-成果包.json`,
                    "application/json;charset=utf-8",
                    JSON.stringify(result, null, 2),
                  )}
                  type="button"
                >
                  导出 JSON
                </button>
                <button className="button-secondary" disabled={Boolean(busy)} onClick={() => void exportText("markdown")} type="button">
                  {busy === "markdown" ? "导出中…" : "导出 Markdown"}
                </button>
                <button className="button-secondary" disabled={Boolean(busy)} onClick={() => void exportText("sku-csv")} type="button">
                  {busy === "sku-csv" ? "导出中…" : "导出 SKU CSV"}
                </button>
              </div>
              <div className="mt-6 border-t border-stone-200 pt-5">
                <label className="form-label">
                  典型案例名称
                  <input className="form-input" onChange={(event) => setCaseName(event.target.value)} value={caseName} />
                </label>
                <button
                  className="button-primary mt-3"
                  disabled={result.blockers.length > 0 || Boolean(busy) || !caseName.trim()}
                  onClick={() => void saveKnowledgeCase()}
                  type="button"
                >
                  {busy === "case" ? "保存中…" : "人工确认并沉淀案例"}
                </button>
              </div>
            </article>

            <article className="panel p-6">
              <h2 className="text-xl font-black">运营确认的生图结果</h2>
              {result.confirmed_images.length === 0 && (
                <p className="mt-4 text-sm text-stone-500">暂无。请在 AI 生图完成真实性、缩略图和合规检查后，由运营确认。</p>
              )}
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                {result.confirmed_images.map((item) => (
                  <div className="overflow-hidden rounded-2xl border border-stone-200" key={item.output_id}>
                    {(item.preview_data_url || item.provider_url) ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        alt="运营确认的商品场景图"
                        className="aspect-square w-full bg-stone-100 object-contain"
                        src={item.preview_data_url || item.provider_url || ""}
                      />
                    ) : (
                      <div className="grid aspect-square place-items-center bg-stone-100 text-sm text-stone-500">结果已登记</div>
                    )}
                    <div className="p-4 text-xs text-stone-600">
                      <p className="font-bold text-stone-900">{item.provider} · {item.model}</p>
                      <p className="mt-2 line-clamp-3">{item.revised_prompt || "沿用运营确认提示词"}</p>
                    </div>
                  </div>
                ))}
              </div>
            </article>
          </section>

          <section className="mt-6 grid gap-6 xl:grid-cols-2">
            <article className="panel p-6">
              <h2 className="text-xl font-black">定稿内容</h2>
              {Object.keys(result.final_content).length === 0 && (
                <p className="mt-4 text-sm text-stone-500">暂无定稿内容。</p>
              )}
              <div className="mt-4 grid gap-4">
                {Object.entries(result.final_content).map(([type, content]) => (
                  <div className="rounded-2xl border border-stone-200 p-4" key={type}>
                    <p className="font-black">{type}</p>
                    <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl bg-stone-50 p-3 text-xs">
                      {JSON.stringify(content, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </article>

            <article className="panel p-6">
              <h2 className="text-xl font-black">项目操作时间线</h2>
              <div className="mt-4 grid max-h-[36rem] gap-3 overflow-auto pr-1">
                {result.timeline.map((event) => (
                  <div className="rounded-2xl border border-stone-200 p-4" key={event.id}>
                    <div className="flex items-center justify-between gap-3">
                      <p className="font-black">{ACTION_LABELS[event.action] || event.action}</p>
                      <span className="text-xs text-stone-500">{new Date(event.created_at).toLocaleString("zh-CN")}</span>
                    </div>
                    {Object.keys(event.summary).length > 0 && (
                      <p className="mt-2 break-all text-xs text-stone-500">{JSON.stringify(event.summary)}</p>
                    )}
                  </div>
                ))}
              </div>
            </article>
          </section>
        </>
      )}
    </AccessGate>
  );
}
