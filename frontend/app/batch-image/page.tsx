"use client";

import { useCallback, useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";

import { AccessGate } from "@/components/access-gate";
import {
  API_BASE_URL,
  TOKEN_STORAGE_KEY,
  apiRequest,
  fileToDataUrl,
  jsonBody,
  sha256File,
  type Asset,
  type BatchImageItem,
  type BatchImageMode,
  type BatchImageTask,
  type Project,
  type ProjectDetail,
} from "@/lib/api";

const modeCopy: Record<BatchImageMode, { label: string; description: string }> = {
  replace_product: {
    label: "批量替换商品",
    description: "把同一真实商品替换进多张场景图，保留原场景、构图和光照。",
  },
  custom_edit: {
    label: "同一指令批量改图",
    description: "把一条运营修改说明应用到多张图片，同时锁定商品事实。",
  },
  resize: {
    label: "批量改尺寸",
    description: "智能重排到统一尺寸，商品、文字和关键版式不变形、不裁切。",
  },
};

const terminalStatuses = new Set(["succeeded", "partial", "failed", "cancelled"]);

type Runtime = {
  provider: string;
  model: string;
  configured: boolean;
  paid_requests_enabled: boolean;
};

function ReviewEditor({
  taskId,
  item,
  onUpdated,
}: {
  taskId: string;
  item: BatchImageItem;
  onUpdated: (item: BatchImageItem) => void;
}) {
  const [checks, setChecks] = useState({
    product_facts_match: false,
    geometry_and_count_match: false,
    logo_text_and_personalization_match: false,
    thumbnail_readable: false,
  });
  const [risk, setRisk] = useState("clear");
  const [notes, setNotes] = useState("");
  const [mediumReason, setMediumReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submitReview(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const updated = await apiRequest<BatchImageItem>(
        `/batch-image-tasks/${taskId}/items/${item.id}/review`,
        {
          method: "POST",
          ...jsonBody({
            expected_revision: item.revision,
            ...checks,
            compliance_risk: risk,
            notes,
            retain_medium_risk_reason: risk === "medium" ? mediumReason : null,
          }),
        },
      );
      onUpdated(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "检查结果保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError("");
    try {
      const updated = await apiRequest<BatchImageItem>(
        `/batch-image-tasks/${taskId}/items/${item.id}/confirm`,
        { method: "POST", ...jsonBody({ expected_revision: item.revision }) },
      );
      onUpdated(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选图确认失败");
    } finally {
      setBusy(false);
    }
  }

  if (item.confirmed_at) {
    return <p className="notice-success mt-4">已由运营逐项确认，已保存到项目素材；没有自动发布或 ERP 写回。</p>;
  }
  if (item.reviewed_at) {
    const canConfirm = item.qa_status === "passed" && ["clear", "medium_resolved"].includes(item.compliance_status);
    return (
      <div className="mt-4 rounded-2xl border border-stone-200 p-4">
        <p className="text-sm font-black">检查记录已保存（不可覆盖）</p>
        <p className="mt-2 text-xs text-stone-600">真实性/缩略图：{item.qa_status} · 合规：{item.compliance_status}</p>
        {canConfirm ? (
          <button className="button-primary mt-3" disabled={busy} onClick={() => void confirm()} type="button">
            {busy ? "确认中…" : "运营确认该结果"}
          </button>
        ) : (
          <p className="notice-error mt-3">该候选未通过门禁，不能确认。请新建任务生成新候选。</p>
        )}
        {error && <p className="notice-error mt-3">{error}</p>}
      </div>
    );
  }

  return (
    <form className="mt-4 rounded-2xl border border-stone-200 p-4" onSubmit={submitReview}>
      <p className="text-sm font-black">运营逐图验收</p>
      <div className="mt-3 grid gap-2 text-sm">
        {[
          ["product_facts_match", "商品事实与参考图一致"],
          ["geometry_and_count_match", "结构、比例与数量一致"],
          ["logo_text_and_personalization_match", "Logo、文字与个性化信息一致"],
          ["thumbnail_readable", "缩略图主体清楚且未关键裁切"],
        ].map(([key, label]) => (
          <label className="flex items-center gap-2" key={key}>
            <input
              checked={checks[key as keyof typeof checks]}
              onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))}
              type="checkbox"
            />
            {label}
          </label>
        ))}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <select className="form-input" onChange={(event) => setRisk(event.target.value)} value={risk}>
          <option value="clear">合规无风险</option>
          <option value="medium">中风险（填写保留理由）</option>
          <option value="high">高风险（永久阻断该候选）</option>
        </select>
        <input className="form-input" minLength={10} onChange={(event) => setNotes(event.target.value)} placeholder="检查说明，至少 10 个字" required value={notes} />
      </div>
      {risk === "medium" && (
        <textarea className="form-input mt-3 min-h-20" minLength={10} onChange={(event) => setMediumReason(event.target.value)} placeholder="中风险保留理由，至少 10 个字" required value={mediumReason} />
      )}
      <button className="button-secondary mt-3" disabled={busy} type="submit">{busy ? "保存中…" : "保存不可覆盖的检查记录"}</button>
      {error && <p className="notice-error mt-3">{error}</p>}
    </form>
  );
}

export default function BatchImagePage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [tasks, setTasks] = useState<BatchImageTask[]>([]);
  const [task, setTask] = useState<BatchImageTask | null>(null);
  const [mode, setMode] = useState<BatchImageMode>("custom_edit");
  const [referenceIds, setReferenceIds] = useState<string[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const [size, setSize] = useState("1024x1024");
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadProject = useCallback(async (id: string) => {
    if (!id) {
      setDetail(null);
      setTasks([]);
      setTask(null);
      return;
    }
    try {
      const [nextDetail, history] = await Promise.all([
        apiRequest<ProjectDetail>(`/projects/${id}`),
        apiRequest<BatchImageTask[]>(`/batch-image-tasks?project_id=${encodeURIComponent(id)}`),
      ]);
      setDetail(nextDetail);
      setTasks(history);
      setTask((current) => current && current.project_id === id ? current : history[0] ?? null);
      const references = nextDetail.assets.filter((asset) => asset.asset_type === "product_reference");
      setReferenceIds((current) => current.filter((value) => references.some((asset) => asset.id === value)));
      setSourceIds((current) => current.filter((value) => nextDetail.assets.some((asset) => asset.id === value)));
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量改图项目加载失败");
    }
  }, []);

  useEffect(() => {
    Promise.all([
      apiRequest<Project[]>("/projects"),
      apiRequest<Runtime>("/config/image-runtime"),
    ])
      .then(([projectRows, runtimeState]) => {
        setProjects(projectRows);
        setRuntime(runtimeState);
        const requestedProject = new URLSearchParams(window.location.search).get("project");
        const initialProject = projectRows.find((item) => item.id === requestedProject) ?? projectRows[0];
        if (initialProject) setProjectId(initialProject.id);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "初始化失败"));
  }, []);

  useEffect(() => {
    void loadProject(projectId);
  }, [loadProject, projectId]);

  useEffect(() => {
    if (!task || terminalStatuses.has(task.status)) return;
    const timer = window.setInterval(() => {
      apiRequest<BatchImageTask>(`/batch-image-tasks/${task.id}`)
        .then((updated) => {
          setTask(updated);
          if (terminalStatuses.has(updated.status)) void loadProject(updated.project_id);
        })
        .catch((caught) => setError(caught instanceof Error ? caught.message : "任务状态刷新失败"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [loadProject, task]);

  const referenceAssets = useMemo(
    () => detail?.assets.filter((asset) => asset.asset_type === "product_reference" && asset.file_hash) ?? [],
    [detail],
  );
  const sourceAssets = useMemo(
    () => detail?.assets.filter((asset) => asset.file_url && asset.file_hash && asset.asset_type !== "generated_image") ?? [],
    [detail],
  );
  const assetById = useMemo(() => new Map((detail?.assets ?? []).map((asset) => [asset.id, asset])), [detail]);

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>, assetType: "product_reference" | "product_raw") {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!projectId || !files.length) return;
    if (files.some((file) => file.size > 1_200_000)) {
      setError("当前本地体验版单张图片上限为 1.2MB，请压缩后上传。");
      return;
    }
    setBusy(assetType === "product_reference" ? "upload-reference" : "upload-source");
    setError("");
    try {
      for (const file of files.slice(0, 10)) {
        await apiRequest<Asset>(`/projects/${projectId}/assets`, {
          method: "POST",
          ...jsonBody({
            asset_type: assetType,
            file_url: await fileToDataUrl(file),
            file_hash: await sha256File(file),
            mime_type: file.type,
            file_size: file.size,
            usage_note: assetType === "product_reference" ? "批量改图商品保真参考" : "批量改图待处理图片",
          }),
        });
      }
      setMessage(`${files.length} 张图片已上传，请勾选后提交任务。`);
      await loadProject(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "图片上传失败");
    } finally {
      setBusy("");
    }
  }

  function toggle(values: string[], setValues: (next: string[]) => void, id: string, checked: boolean, cap: number) {
    if (checked && values.length >= cap) {
      setError(`最多选择 ${cap} 张图片`);
      return;
    }
    setValues(checked ? [...values, id] : values.filter((value) => value !== id));
  }

  async function createTask() {
    if (!detail?.product_card?.confirmed_at) {
      setError("批量改图前必须先到商品项目确认商品信息卡。");
      return;
    }
    if (!referenceIds.length || !sourceIds.length) {
      setError("请至少选择 1 张商品参考图和 1 张待处理图片。");
      return;
    }
    if (mode === "custom_edit" && !instruction.trim()) {
      setError("同一指令批量改图必须填写修改说明。");
      return;
    }
    if (runtime?.paid_requests_enabled && !window.confirm(`将向 ${runtime.provider}/${runtime.model} 发送 ${sourceIds.length} 次真实图片编辑请求，可能产生费用。是否继续？`)) return;
    setBusy("create");
    setError("");
    setMessage("");
    try {
      const created = await apiRequest<BatchImageTask>("/batch-image-tasks", {
        method: "POST",
        ...jsonBody({
          project_id: projectId,
          mode,
          product_reference_asset_ids: referenceIds,
          source_asset_ids: sourceIds,
          instruction,
          size,
          idempotency_key: `batch-${crypto.randomUUID()}`,
        }),
      });
      setTask(created);
      setMessage("批量任务已创建，正在逐张处理。每张结果仍需运营验收。 ");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量任务创建失败");
    } finally {
      setBusy("");
    }
  }

  function updateItem(updated: BatchImageItem) {
    setTask((current) => current ? { ...current, items: current.items.map((item) => item.id === updated.id ? updated : item) } : current);
  }

  async function downloadConfirmed() {
    if (!task) return;
    const response = await fetch(`${API_BASE_URL}/batch-image-tasks/${task.id}/download`, {
      headers: { Authorization: `Bearer ${window.localStorage.getItem(TOKEN_STORAGE_KEY) ?? ""}` },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({})) as { detail?: string };
      setError(payload.detail ?? "批量下载失败");
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `batch-${task.id}-confirmed.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <AccessGate requiredRole="operator">
      <div className="page-wrap">
        <section className="panel p-6 md:p-8">
          <p className="eyebrow">运营监督式批处理</p>
          <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
            <div>
              <h1 className="text-3xl font-black">批量修改图片</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">一次最多处理 10 张。系统不会定时无人值守执行，也不会把 AI 输出自动当成最终图片；每张结果都要由运营逐项检查和确认。</p>
            </div>
            <select className="form-input min-w-64" onChange={(event) => { setProjectId(event.target.value); setTask(null); setReferenceIds([]); setSourceIds([]); }} value={projectId}>
              <option value="">选择商品项目</option>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name} · {project.store_name}</option>)}
            </select>
          </div>
          {runtime && <p className={runtime.paid_requests_enabled ? "notice-error mt-5" : "notice-success mt-5"}>当前图片服务：{runtime.provider} / {runtime.model}。{runtime.paid_requests_enabled ? "提交后会按待处理图片张数发出真实请求并可能收费。" : "Mock 模式，不会发出付费请求。"}</p>}
          {message && <p className="notice-success mt-5">{message}</p>}
          {error && <p className="notice-error mt-5">{error}</p>}
        </section>

        {detail && (
          <>
            <section className="panel mt-6 p-6">
              <div className="grid gap-3 md:grid-cols-3">
                {(Object.keys(modeCopy) as BatchImageMode[]).map((key) => (
                  <button className={`rounded-2xl border p-4 text-left ${mode === key ? "border-emerald-500 bg-emerald-50" : "border-stone-200 bg-white"}`} key={key} onClick={() => setMode(key)} type="button">
                    <p className="font-black">{modeCopy[key].label}</p>
                    <p className="mt-2 text-xs leading-5 text-stone-600">{modeCopy[key].description}</p>
                  </button>
                ))}
              </div>
              <div className="mt-5 grid gap-5 lg:grid-cols-2">
                <ImagePicker title={`商品保真参考图（${referenceIds.length}/3）`} assets={referenceAssets} selected={referenceIds} onToggle={(id, checked) => toggle(referenceIds, setReferenceIds, id, checked, 3)} />
                <ImagePicker title={`待处理图片（${sourceIds.length}/10）`} assets={sourceAssets} selected={sourceIds} onToggle={(id, checked) => toggle(sourceIds, setSourceIds, id, checked, 10)} />
              </div>
              <div className="mt-4 flex flex-wrap gap-3">
                <label className="button-secondary cursor-pointer">{busy === "upload-reference" ? "上传中…" : "上传商品参考图"}<input accept="image/jpeg,image/png,image/webp" className="hidden" disabled={Boolean(busy)} multiple onChange={(event) => void uploadFiles(event, "product_reference")} type="file" /></label>
                <label className="button-secondary cursor-pointer">{busy === "upload-source" ? "上传中…" : "上传待处理图片"}<input accept="image/jpeg,image/png,image/webp" className="hidden" disabled={Boolean(busy)} multiple onChange={(event) => void uploadFiles(event, "product_raw")} type="file" /></label>
              </div>
              <div className="mt-5 grid gap-3 md:grid-cols-[1fr_180px_auto]">
                <input className="form-input" maxLength={2000} onChange={(event) => setInstruction(event.target.value)} placeholder={mode === "custom_edit" ? "必填：例如统一换成自然光厨房背景，商品保持原样" : "可选：补充不改变商品事实的修改要求"} value={instruction} />
                <select className="form-input" onChange={(event) => setSize(event.target.value)} value={size}>
                  <option value="1024x1024">1:1 · 1024×1024</option>
                  <option value="1536x1024">3:2 · 1536×1024</option>
                  <option value="1024x1536">2:3 · 1024×1536</option>
                  <option value="1280x720">16:9 · 1280×720</option>
                  <option value="720x1280">9:16 · 720×1280</option>
                </select>
                <button className="button-primary" disabled={Boolean(busy) || !runtime?.configured} onClick={() => void createTask()} type="button">{busy === "create" ? "创建中…" : `开始处理 ${sourceIds.length} 张`}</button>
              </div>
              <p className="mt-3 text-xs text-stone-500">商品参考图始终作为视觉事实源；运营修改说明不能覆盖结构、比例、材质、颜色、数量、Logo、文字和个性化信息。</p>
            </section>

            {tasks.length > 0 && <section className="panel mt-6 p-6"><p className="eyebrow">任务历史</p><div className="mt-3 flex flex-wrap gap-2">{tasks.slice(0, 12).map((row) => <button className={task?.id === row.id ? "button-primary" : "button-secondary"} key={row.id} onClick={() => setTask(row)} type="button">{modeCopy[row.mode].label} · {row.progress_done}/{row.progress_total} · {row.status}</button>)}</div></section>}

            {task && (
              <section className="panel mt-6 p-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div><p className="eyebrow">{modeCopy[task.mode].label}</p><h2 className="mt-2 text-2xl font-black">任务 {task.progress_done}/{task.progress_total} · {task.status}</h2><p className="mt-1 text-xs text-stone-500">{task.provider} / {task.model} · 成功 {task.succeeded_count} · 失败 {task.failed_count}</p></div>
                  <button className="button-secondary" onClick={() => void downloadConfirmed()} type="button">下载已确认结果 ZIP</button>
                </div>
                {task.error_message && <p className="notice-error mt-4">{task.error_message}</p>}
                <div className="mt-6 grid gap-6">
                  {task.items.map((item) => {
                    const source = item.source_asset_id ? assetById.get(item.source_asset_id) : undefined;
                    return (
                      <article className="rounded-3xl border border-stone-200 p-5" key={item.id}>
                        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-black">第 {item.position} 张 · {item.status}</h3><span className="status-chip">QA {item.qa_status} · 合规 {item.compliance_status}</span></div>
                        <div className="mt-4 grid gap-4 md:grid-cols-2">
                          <figure><figcaption className="mb-2 text-xs font-bold text-stone-500">原图</figcaption>{source?.file_url ? <img alt="批量改图原图" className="max-h-96 w-full rounded-2xl border object-contain" src={source.file_url} /> : <div className="rounded-2xl bg-stone-100 p-10 text-center text-sm text-stone-500">原图快照已保留在任务记录</div>}</figure>
                          <figure><figcaption className="mb-2 text-xs font-bold text-stone-500">AI 候选图（未确认前不是最终结果）</figcaption>{item.preview_data_url ? <img alt="批量改图候选" className="max-h-96 w-full rounded-2xl border object-contain" src={item.preview_data_url} /> : <div className="rounded-2xl bg-stone-100 p-10 text-center text-sm text-stone-500">{item.error_message || "正在生成…"}</div>}</figure>
                        </div>
                        {item.status === "succeeded" && <ReviewEditor item={item} onUpdated={updateItem} taskId={task.id} />}
                      </article>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </AccessGate>
  );
}

function ImagePicker({ title, assets, selected, onToggle }: { title: string; assets: Asset[]; selected: string[]; onToggle: (id: string, checked: boolean) => void }) {
  return (
    <div className="rounded-2xl border border-stone-200 p-4">
      <p className="font-black">{title}</p>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {assets.map((asset) => (
          <label className={`cursor-pointer overflow-hidden rounded-xl border ${selected.includes(asset.id) ? "border-emerald-500 ring-2 ring-emerald-100" : "border-stone-200"}`} key={asset.id}>
            {asset.file_url && <img alt="项目图片素材" className="aspect-square w-full object-contain" src={asset.file_url} />}
            <span className="flex items-center gap-2 px-2 py-2 text-xs"><input checked={selected.includes(asset.id)} onChange={(event) => onToggle(asset.id, event.target.checked)} type="checkbox" />选择</span>
          </label>
        ))}
      </div>
      {!assets.length && <p className="mt-3 text-sm text-stone-500">暂无可用图片，请先上传。</p>}
    </div>
  );
}
