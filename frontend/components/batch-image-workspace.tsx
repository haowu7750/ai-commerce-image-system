"use client";

import Link from "next/link";
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
  type BatchImageTask,
  type Project,
  type ProjectDetail,
} from "@/lib/api";
import { batchToolByMode, type SupportedBatchMode } from "@/lib/batch-image-tools";

type Runtime = {
  provider: string;
  model: string;
  configured: boolean;
  paid_requests_enabled: boolean;
};

type StatusFilter = "all" | "processing" | "completed" | "failed";

const terminalStatuses = new Set(["succeeded", "partial", "failed", "cancelled"]);
const statusCopy: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
};

export function BatchImageWorkspace({ mode }: { mode: SupportedBatchMode }) {
  const tool = batchToolByMode[mode];
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [tasks, setTasks] = useState<BatchImageTask[]>([]);
  const [activeTask, setActiveTask] = useState<BatchImageTask | null>(null);
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [referenceIds, setReferenceIds] = useState<string[]>([]);
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [secondaryIds, setSecondaryIds] = useState<string[]>([]);
  const [instruction, setInstruction] = useState("");
  const [category, setCategory] = useState("通用类目");
  const [printCarrier, setPrintCarrier] = useState("服装");
  const [subject, setSubject] = useState("");
  const [overallCount, setOverallCount] = useState(4);
  const [detailCount, setDetailCount] = useState(1);
  const [size, setSize] = useState("1024x1024");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadProject = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const [projectDetail, history] = await Promise.all([
        apiRequest<ProjectDetail>(`/projects/${id}`),
        apiRequest<BatchImageTask[]>(
          `/batch-image-tasks?project_id=${encodeURIComponent(id)}&mode=${mode}`,
        ),
      ]);
      setDetail(projectDetail);
      setTasks(history);
      setSelectedTaskIds((current) => current.filter((taskId) => history.some((task) => task.id === taskId)));
      setActiveTask((current) => {
        if (!current || current.project_id !== id || current.mode !== mode) return null;
        return history.find((task) => task.id === current.id) ?? current;
      });
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "批量任务加载失败");
    }
  }, [mode]);

  useEffect(() => {
    Promise.all([apiRequest<Project[]>("/projects"), apiRequest<Runtime>("/config/image-runtime")])
      .then(([rows, provider]) => {
        setProjects(rows);
        setRuntime(provider);
        const requested = new URLSearchParams(window.location.search).get("project");
        const initial = rows.find((item) => item.id === requested) ?? rows[0];
        if (initial) setProjectId(initial.id);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "初始化失败"));
  }, []);

  useEffect(() => {
    void loadProject(projectId);
  }, [loadProject, projectId]);

  useEffect(() => {
    if (!activeTask || terminalStatuses.has(activeTask.status)) return;
    const timer = window.setInterval(() => {
      apiRequest<BatchImageTask>(`/batch-image-tasks/${activeTask.id}`)
        .then((updated) => {
          setActiveTask(updated);
          if (terminalStatuses.has(updated.status)) void loadProject(updated.project_id);
        })
        .catch((caught) => setError(caught instanceof Error ? caught.message : "任务状态刷新失败"));
    }, 1200);
    return () => window.clearInterval(timer);
  }, [activeTask, loadProject]);

  const assetById = useMemo(
    () => new Map((detail?.assets ?? []).filter((asset) => !asset.is_archived).map((asset) => [asset.id, asset])),
    [detail],
  );
  const selectableAssets = useMemo(
    () => [...assetById.values()].filter((asset) => asset.file_url && asset.file_hash && asset.asset_type !== "generated_image"),
    [assetById],
  );
  const productReferences = useMemo(
    () => selectableAssets.filter((asset) => asset.asset_type === "product_reference"),
    [selectableAssets],
  );
  const filteredTasks = useMemo(() => tasks.filter((task) => {
    if (statusFilter === "processing") return ["queued", "running"].includes(task.status);
    if (statusFilter === "completed") return ["succeeded", "partial"].includes(task.status);
    if (statusFilter === "failed") return task.status === "failed";
    return true;
  }), [statusFilter, tasks]);

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>, target: "reference" | "source" | "secondary") {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!projectId || !files.length) return;
    if (files.some((file) => file.size > 1_200_000)) {
      setError("当前本地体验版单张图片上限为 1.2MB，请压缩后上传。");
      return;
    }
    setBusy(`upload-${target}`);
    setError("");
    try {
      const created: string[] = [];
      const maxFiles = target === "reference" ? 1 : target === "source" && mode === "angle_fission" ? 5 : 10;
      for (const file of files.slice(0, maxFiles)) {
        const assetType = target === "reference" && ["scene_replace", "buyer_show"].includes(mode)
          ? "product_reference"
          : "product_raw";
        const asset = await apiRequest<Asset>(`/projects/${projectId}/assets`, {
          method: "POST",
          ...jsonBody({
            asset_type: assetType,
            file_url: await fileToDataUrl(file),
            file_hash: await sha256File(file),
            mime_type: file.type,
            file_size: file.size,
            usage_note: target === "source" ? `${tool.shortTitle}输入图` : `${tool.shortTitle}参考图`,
          }),
        });
        created.push(asset.id);
      }
      if (target === "reference") setReferenceIds(created.slice(0, 1));
      if (target === "source") setSourceIds((current) => [...current, ...created].slice(0, mode === "angle_fission" ? 5 : 10));
      if (target === "secondary") setSecondaryIds((current) => [...current, ...created].slice(0, 10));
      await loadProject(projectId);
      setMessage(`已上传 ${created.length} 张图片。`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "图片上传失败");
    } finally {
      setBusy("");
    }
  }

  async function createTask() {
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
          secondary_asset_ids: secondaryIds,
          instruction,
          size,
          category,
          print_carrier: mode === "pattern_extract" ? printCarrier : null,
          subject: mode === "angle_fission" ? subject : null,
          overall_count: overallCount,
          detail_count: detailCount,
          idempotency_key: `${mode}-${crypto.randomUUID()}`,
        }),
      });
      setActiveTask(created);
      setMessage("任务已创建，正在后台逐张处理。完成后请逐图验收。");
      await loadProject(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务创建失败");
    } finally {
      setBusy("");
    }
  }

  async function archiveTasks(taskIds: string[]) {
    if (!taskIds.length || !window.confirm(`确定删除所选 ${taskIds.length} 个任务吗？这是软删除，审计记录会保留。`)) return;
    setBusy("archive");
    setError("");
    try {
      await apiRequest("/batch-image-tasks/archive-selection", {
        method: "POST",
        ...jsonBody({ task_ids: taskIds }),
      });
      setSelectedTaskIds([]);
      if (activeTask && taskIds.includes(activeTask.id)) setActiveTask(null);
      await loadProject(projectId);
      setMessage("任务已移入已删除记录，图片结果和审计链未被物理清除。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "任务删除失败");
    } finally {
      setBusy("");
    }
  }

  async function downloadTasks(taskIds: string[]) {
    if (!taskIds.length) return;
    setBusy("download");
    setError("");
    try {
      const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
      const response = await fetch(`${API_BASE_URL}/batch-image-tasks/download-selection`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ task_ids: taskIds }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { detail?: string };
        throw new Error(payload.detail ?? "下载失败");
      }
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${tool.mode}-confirmed.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "下载失败");
    } finally {
      setBusy("");
    }
  }

  function updateItem(updated: BatchImageItem) {
    setActiveTask((current) => current ? {
      ...current,
      items: current.items.map((item) => item.id === updated.id ? updated : item),
    } : current);
    void loadProject(projectId);
  }

  const createDisabled = !runtime?.configured || !projectId || !sourceIds.length
    || (["scene_replace", "buyer_show"].includes(mode) && referenceIds.length !== 1)
    || (mode === "custom_edit" && !instruction.trim())
    || (mode === "custom_edit" && secondaryIds.length > 0 && secondaryIds.length !== sourceIds.length)
    || (mode === "angle_fission" && !subject.trim());

  return (
    <AccessGate requiredRole="operator">
      <div className="mx-auto max-w-[1600px]">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-4">
            <Link className="mt-1 grid h-10 w-10 place-items-center rounded-xl border border-stone-200 bg-white text-xl" href="/batch-image" aria-label="返回批量工具">←</Link>
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-3xl font-black tracking-tight md:text-4xl">{tool.title}</h1>
                <span className="rounded-xl border border-indigo-200 bg-indigo-50 px-3 py-1 text-sm font-black text-indigo-600">运营监督版</span>
              </div>
              <p className="mt-3 text-sm leading-6 text-stone-600">{tool.description}</p>
            </div>
          </div>
          <div className="rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm">
            <span className="font-black">当前模型：</span>{runtime?.provider ?? "检测中"} / {runtime?.model ?? "—"}
          </div>
        </header>

        <section className="mt-7 rounded-[26px] border border-stone-200 bg-white p-5 shadow-card">
          <div className="grid gap-4 xl:grid-cols-[220px_1fr]">
            <label className="form-label">项目
              <select className="form-input" value={projectId} onChange={(event) => {
                setProjectId(event.target.value);
                setReferenceIds([]); setSourceIds([]); setSecondaryIds([]); setActiveTask(null);
              }}>
                {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
              </select>
            </label>
            <CreateFields
              mode={mode}
              assets={selectableAssets}
              productReferences={productReferences}
              assetById={assetById}
              referenceIds={referenceIds}
              sourceIds={sourceIds}
              secondaryIds={secondaryIds}
              category={category}
              printCarrier={printCarrier}
              subject={subject}
              overallCount={overallCount}
              detailCount={detailCount}
              size={size}
              instruction={instruction}
              busy={busy}
              onUpload={uploadFiles}
              onReferenceIds={setReferenceIds}
              onSourceIds={setSourceIds}
              onSecondaryIds={setSecondaryIds}
              onCategory={setCategory}
              onPrintCarrier={setPrintCarrier}
              onSubject={setSubject}
              onOverallCount={setOverallCount}
              onDetailCount={setDetailCount}
              onSize={setSize}
              onInstruction={setInstruction}
            />
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-stone-100 pt-5">
            <p className="text-xs leading-5 text-stone-500">立即执行 · 最多 10 张 · 候选图必须逐张验收 · 不自动发布</p>
            <button className="button-primary !bg-indigo-600 hover:!bg-indigo-700" disabled={Boolean(busy) || createDisabled} onClick={() => void createTask()} type="button">
              {busy === "create" ? "创建中…" : `▶ 创建任务（${sourceIds.length} 张输入）`}
            </button>
          </div>
        </section>

        {message && <p className="notice-success mt-5">{message}</p>}
        {error && <p className="notice-error mt-5">{error}</p>}
        {!runtime?.configured && <p className="notice-error mt-5">图片 Provider 未配置，任务创建已禁用。</p>}

        <section className="mt-7">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-stone-200">
            <div className="flex gap-5 overflow-x-auto">
              {(["all", "processing", "completed", "failed"] as StatusFilter[]).map((filter) => {
                const labels = { all: "全部", processing: "处理中", completed: "已完成", failed: "失败" };
                const count = tasks.filter((task) => filter === "all" || (filter === "processing" ? ["queued", "running"].includes(task.status) : filter === "completed" ? ["succeeded", "partial"].includes(task.status) : task.status === "failed")).length;
                return <button className={`border-b-2 px-1 pb-3 text-sm font-bold ${statusFilter === filter ? "border-indigo-600 text-indigo-600" : "border-transparent text-stone-500"}`} key={filter} onClick={() => setStatusFilter(filter)} type="button">{labels[filter]} ({count})</button>;
              })}
            </div>
            <div className="mb-3 flex gap-2">
              <button className="button-secondary" disabled={!selectedTaskIds.length || Boolean(busy)} onClick={() => void downloadTasks(selectedTaskIds)} type="button">↓ 批量下载</button>
              <button className="button-secondary" disabled={!selectedTaskIds.length || Boolean(busy)} onClick={() => void archiveTasks(selectedTaskIds)} type="button">删除所选</button>
            </div>
          </div>

          <TaskTable
            tasks={filteredTasks}
            assetById={assetById}
            selectedIds={selectedTaskIds}
            onSelectedIds={setSelectedTaskIds}
            onOpen={setActiveTask}
            onDownload={(taskId) => void downloadTasks([taskId])}
            onArchive={(taskId) => void archiveTasks([taskId])}
          />
        </section>

        {activeTask && <TaskDetail task={activeTask} assetById={assetById} onClose={() => setActiveTask(null)} onUpdated={updateItem} />}
      </div>
    </AccessGate>
  );
}

type CreateFieldsProps = {
  mode: SupportedBatchMode;
  assets: Asset[];
  productReferences: Asset[];
  assetById: Map<string, Asset>;
  referenceIds: string[];
  sourceIds: string[];
  secondaryIds: string[];
  category: string;
  printCarrier: string;
  subject: string;
  overallCount: number;
  detailCount: number;
  size: string;
  instruction: string;
  busy: string;
  onUpload: (event: ChangeEvent<HTMLInputElement>, target: "reference" | "source" | "secondary") => Promise<void>;
  onReferenceIds: (ids: string[]) => void;
  onSourceIds: (ids: string[]) => void;
  onSecondaryIds: (ids: string[]) => void;
  onCategory: (value: string) => void;
  onPrintCarrier: (value: string) => void;
  onSubject: (value: string) => void;
  onOverallCount: (value: number) => void;
  onDetailCount: (value: number) => void;
  onSize: (value: string) => void;
  onInstruction: (value: string) => void;
};

function CreateFields(props: CreateFieldsProps) {
  const needsProduct = ["scene_replace", "buyer_show"].includes(props.mode);
  const isCustom = props.mode === "custom_edit";
  const sourceTitle = props.mode === "pattern_extract" ? "印花商品原图" : props.mode === "angle_fission" ? "产品场景图" : isCustom ? "参考图一（必填）" : needsProduct ? "场景图" : "待改尺寸图片";
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {!["resize", "angle_fission", "pattern_extract"].includes(props.mode) && (
        <UploadField
          title={isCustom ? "固定参考图（可选）" : "商品图（1 张）"}
          note={isCustom ? "整批共用，每张都会参照它" : "商品外观事实来源"}
          assets={needsProduct ? props.productReferences : props.assets}
          selectedIds={props.referenceIds}
          max={1}
          busy={props.busy === "upload-reference"}
          onChange={props.onReferenceIds}
          onUpload={(event) => props.onUpload(event, "reference")}
        />
      )}
      {props.mode === "pattern_extract" && (
        <label className="form-label">印花载体
          <select className="form-input" value={props.printCarrier} onChange={(event) => props.onPrintCarrier(event.target.value)}>
            <option>服装</option><option>平铺面料</option><option>杯具/曲面</option><option>包装盒</option><option>其他</option>
          </select>
        </label>
      )}
      {needsProduct && <label className="form-label">类目
        <input className="form-input" value={props.category} onChange={(event) => props.onCategory(event.target.value)} placeholder="例如：家居日用" />
      </label>}
      {props.mode === "angle_fission" && <>
        <label className="form-label">拍摄主体
          <input className="form-input" value={props.subject} onChange={(event) => props.onSubject(event.target.value)} placeholder="例如：沙发" />
        </label>
        <label className="form-label">整体图数量
          <select className="form-input" value={props.overallCount} onChange={(event) => props.onOverallCount(Number(event.target.value))}>{[0,1,2,3,4,5,6].map((count) => <option key={count}>{count}</option>)}</select>
        </label>
        <label className="form-label">细节图数量
          <select className="form-input" value={props.detailCount} onChange={(event) => props.onDetailCount(Number(event.target.value))}>{[0,1,2,3,4].map((count) => <option key={count}>{count}</option>)}</select>
        </label>
      </>}
      <UploadField
        title={sourceTitle}
        note={props.mode === "angle_fission" ? "最多 5 张" : "逐张处理，最多 10 张"}
        assets={props.assets}
        selectedIds={props.sourceIds}
        max={props.mode === "angle_fission" ? 5 : 10}
        busy={props.busy === "upload-source"}
        onChange={props.onSourceIds}
        onUpload={(event) => props.onUpload(event, "source")}
      />
      {isCustom && <UploadField
        title="参考图二（可选）"
        note="与参考图一逐张配对，数量需一致"
        assets={props.assets}
        selectedIds={props.secondaryIds}
        max={10}
        busy={props.busy === "upload-secondary"}
        onChange={props.onSecondaryIds}
        onUpload={(event) => props.onUpload(event, "secondary")}
      />}
      {(["resize", "pattern_extract", "custom_edit"] as SupportedBatchMode[]).includes(props.mode) && <label className="form-label">输出尺寸
        <select className="form-input" value={props.size} onChange={(event) => props.onSize(event.target.value)}>
          <option value="1024x1024">1:1 · 1024×1024</option><option value="1024x1365">3:4 · 1024×1365</option><option value="1365x1024">4:3 · 1365×1024</option><option value="1536x1024">3:2 · 1536×1024</option><option value="1024x1536">2:3 · 1024×1536</option><option value="1280x720">16:9 · 1280×720</option><option value="720x1280">9:16 · 720×1280</option>
        </select>
      </label>}
      {(isCustom || !["resize", "angle_fission"].includes(props.mode)) && <label className="form-label xl:col-span-2">{isCustom ? "批量提示词（必填）" : "补充说明（可选）"}
        <textarea className="form-input min-h-24" maxLength={2000} value={props.instruction} onChange={(event) => props.onInstruction(event.target.value)} placeholder={isCustom ? "描述要对每张图做的操作，不能覆盖商品保真规则" : "补充场景、风格或输出要求"} />
      </label>}
    </div>
  );
}

function UploadField({ title, note, assets, selectedIds, max, busy, onChange, onUpload }: { title: string; note: string; assets: Asset[]; selectedIds: string[]; max: number; busy: boolean; onChange: (ids: string[]) => void; onUpload: (event: ChangeEvent<HTMLInputElement>) => void }) {
  return (
    <div className="min-w-0">
      <p className="text-sm font-bold text-stone-700">{title}</p>
      <label className="mt-1.5 flex min-h-20 cursor-pointer items-center gap-3 rounded-xl border border-dashed border-indigo-200 bg-indigo-50/60 px-4 py-3 text-sm text-indigo-700">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-indigo-200 bg-white text-xl">＋</span>
        <span><b>{busy ? "上传中…" : "点击上传"}</b><small className="mt-1 block text-stone-500">{note}</small></span>
        <input className="hidden" accept="image/jpeg,image/png,image/webp" disabled={busy} multiple={max > 1} onChange={onUpload} type="file" />
      </label>
      <select className="form-input mt-2" value="" onChange={(event) => {
        if (!event.target.value) return;
        onChange(max === 1 ? [event.target.value] : [...new Set([...selectedIds, event.target.value])].slice(0, max));
      }}>
        <option value="">从项目素材中选择…</option>
        {assets.filter((asset) => !selectedIds.includes(asset.id)).map((asset) => <option key={asset.id} value={asset.id}>{asset.usage_note || asset.asset_type} · {asset.id.slice(0, 6)}</option>)}
      </select>
      {selectedIds.length > 0 && <div className="mt-2 flex flex-wrap gap-2">{selectedIds.map((id, index) => <button className="rounded-lg bg-stone-100 px-2 py-1 text-xs" key={id} onClick={() => onChange(selectedIds.filter((value) => value !== id))} type="button">图 {index + 1} ×</button>)}</div>}
    </div>
  );
}

function TaskTable({ tasks, assetById, selectedIds, onSelectedIds, onOpen, onDownload, onArchive }: { tasks: BatchImageTask[]; assetById: Map<string, Asset>; selectedIds: string[]; onSelectedIds: (ids: string[]) => void; onOpen: (task: BatchImageTask) => void; onDownload: (id: string) => void; onArchive: (id: string) => void }) {
  if (!tasks.length) return <div className="mt-6 grid min-h-72 place-items-center rounded-[26px] border border-stone-200 bg-white text-center"><div><span className="text-4xl text-indigo-500">☷</span><h3 className="mt-4 text-xl font-black">暂无该状态任务</h3><p className="mt-2 text-sm text-stone-500">创建后的任务会在这里显示进度、执行批次和结果。</p></div></div>;
  return (
    <div className="mt-6 overflow-x-auto rounded-[26px] border border-stone-200 bg-white shadow-sm">
      <table className="min-w-[1250px] w-full text-left text-sm">
        <thead className="bg-stone-50 text-stone-700"><tr><th className="p-4"><input checked={tasks.every((task) => selectedIds.includes(task.id))} onChange={(event) => onSelectedIds(event.target.checked ? tasks.map((task) => task.id) : [])} type="checkbox" /></th><th>任务/提示词</th><th>输入图</th><th>模型</th><th>状态</th><th>进度</th><th>创建时间</th><th>结果图</th><th className="pr-4">操作</th></tr></thead>
        <tbody>{tasks.map((task) => {
          const sources = task.source_asset_ids.map((id) => assetById.get(id)).filter(Boolean) as Asset[];
          const outputs = task.items.filter((item) => item.preview_data_url).slice(0, 3);
          return <tr className="border-t border-stone-100" key={task.id}>
            <td className="p-4"><input checked={selectedIds.includes(task.id)} onChange={(event) => onSelectedIds(event.target.checked ? [...selectedIds, task.id] : selectedIds.filter((id) => id !== task.id))} type="checkbox" /></td>
            <td className="max-w-72 py-4 pr-4"><p className="line-clamp-2 font-bold">{String(task.options.category ?? "通用类目")}</p><button className="mt-1 text-xs font-bold text-indigo-600 underline" onClick={() => onOpen(task)} type="button">查看详情</button></td>
            <td className="py-4 pr-4"><ThumbnailStrip urls={sources.map((asset) => asset.file_url).filter(Boolean) as string[]} total={sources.length} /></td>
            <td className="py-4 pr-4">{task.model}</td>
            <td className="py-4 pr-4"><span className={`rounded-full px-3 py-1 text-xs font-bold ${task.status === "succeeded" ? "bg-emerald-50 text-emerald-700" : task.status === "failed" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-700"}`}>{statusCopy[task.status] ?? task.status}</span></td>
            <td className="min-w-32 py-4 pr-4"><div className="h-2 rounded-full bg-stone-100"><div className="h-2 rounded-full bg-emerald-500" style={{ width: `${task.progress_total ? Math.round(task.progress_done / task.progress_total * 100) : 0}%` }} /></div><span className="mt-1 block text-xs">{task.progress_done}/{task.progress_total}</span></td>
            <td className="py-4 pr-4 text-xs text-stone-600">{new Date(task.created_at).toLocaleString("zh-CN")}</td>
            <td className="py-4 pr-4"><ThumbnailStrip urls={outputs.map((item) => item.preview_data_url as string)} total={task.items.filter((item) => item.preview_data_url).length} /></td>
            <td className="py-4 pr-4"><div className="flex gap-2"><button className="button-secondary !px-3 !py-2" onClick={() => onDownload(task.id)} type="button">下载</button><button className="button-secondary !px-3 !py-2" disabled={["queued", "running"].includes(task.status)} onClick={() => onArchive(task.id)} type="button">删除</button></div></td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  );
}

function ThumbnailStrip({ urls, total }: { urls: string[]; total: number }) {
  return <div className="flex items-center gap-1">{urls.slice(0, 3).map((url, index) => <img alt="任务缩略图" className="h-14 w-14 rounded-lg border bg-white object-contain" key={`${url.slice(0, 20)}-${index}`} src={url} />)}{total > 3 && <span className="grid h-14 min-w-12 place-items-center rounded-lg border bg-white text-xs">+{total - 3}</span>}</div>;
}

function TaskDetail({ task, assetById, onClose, onUpdated }: { task: BatchImageTask; assetById: Map<string, Asset>; onClose: () => void; onUpdated: (item: BatchImageItem) => void }) {
  return <section className="mt-7 rounded-[28px] border border-indigo-100 bg-white p-6 shadow-card">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow !text-indigo-600">任务详情与运营验收</p><h2 className="mt-2 text-2xl font-black">{statusCopy[task.status]} · {task.progress_done}/{task.progress_total}</h2><p className="mt-1 text-xs text-stone-500">{task.provider} / {task.model} · 成功 {task.succeeded_count} · 失败 {task.failed_count}</p></div><button className="button-secondary" onClick={onClose} type="button">收起详情</button></div>
    {task.error_message && <p className="notice-error mt-4">{task.error_message}</p>}
    <div className="mt-5 grid gap-5 xl:grid-cols-2">{task.items.map((item) => {
      const source = item.source_asset_id ? assetById.get(item.source_asset_id) : undefined;
      return <article className="rounded-2xl border border-stone-200 p-4" key={item.id}>
        <div className="flex items-center justify-between gap-2"><h3 className="font-black">第 {item.position} 张 · {statusCopy[item.status] ?? item.status}</h3><span className="status-chip">QA {item.qa_status} · 合规 {item.compliance_status}</span></div>
        <div className="mt-4 grid grid-cols-2 gap-3"><figure><figcaption className="mb-2 text-xs font-bold text-stone-500">输入图</figcaption>{source?.file_url ? <img alt="输入图" className="aspect-square w-full rounded-xl border object-contain" src={source.file_url} /> : <div className="aspect-square rounded-xl bg-stone-100" />}</figure><figure><figcaption className="mb-2 text-xs font-bold text-stone-500">AI 候选图</figcaption>{item.preview_data_url ? <img alt="AI 候选图" className="aspect-square w-full rounded-xl border object-contain" src={item.preview_data_url} /> : <div className="grid aspect-square place-items-center rounded-xl bg-stone-100 text-xs text-stone-500">{item.error_message ?? "生成中…"}</div>}</figure></div>
        {item.status === "succeeded" && <ReviewEditor taskId={task.id} item={item} onUpdated={onUpdated} />}
      </article>;
    })}</div>
  </section>;
}

function ReviewEditor({ taskId, item, onUpdated }: { taskId: string; item: BatchImageItem; onUpdated: (item: BatchImageItem) => void }) {
  const [checks, setChecks] = useState({ product_facts_match: false, geometry_and_count_match: false, logo_text_and_personalization_match: false, thumbnail_readable: false });
  const [risk, setRisk] = useState("clear");
  const [notes, setNotes] = useState("");
  const [mediumReason, setMediumReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function review(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try { onUpdated(await apiRequest<BatchImageItem>(`/batch-image-tasks/${taskId}/items/${item.id}/review`, { method: "POST", ...jsonBody({ expected_revision: item.revision, ...checks, compliance_risk: risk, notes, retain_medium_risk_reason: risk === "medium" ? mediumReason : null }) })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "检查保存失败"); } finally { setBusy(false); }
  }
  async function confirm() {
    setBusy(true); setError("");
    try { onUpdated(await apiRequest<BatchImageItem>(`/batch-image-tasks/${taskId}/items/${item.id}/confirm`, { method: "POST", ...jsonBody({ expected_revision: item.revision }) })); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "确认失败"); } finally { setBusy(false); }
  }
  if (item.confirmed_at) return <p className="notice-success mt-4">已由运营确认并保存到项目素材；未自动发布或写回 ERP。</p>;
  if (item.reviewed_at) {
    const canConfirm = item.qa_status === "passed" && ["clear", "medium_resolved"].includes(item.compliance_status);
    return <div className="mt-4 rounded-xl border p-3 text-sm"><p className="font-black">检查记录已保存（不可覆盖）</p><p className="mt-1 text-xs">真实性/缩略图：{item.qa_status} · 合规：{item.compliance_status}</p>{canConfirm ? <button className="button-primary mt-3" disabled={busy} onClick={() => void confirm()} type="button">运营确认该结果</button> : <p className="notice-error mt-3">该候选未通过门禁，不能确认。</p>}{error && <p className="notice-error mt-3">{error}</p>}</div>;
  }
  return <form className="mt-4 rounded-xl border p-3" onSubmit={review}><p className="text-sm font-black">运营逐图验收</p><div className="mt-2 grid gap-2 text-xs">{[["product_facts_match", "商品事实与参考图一致"], ["geometry_and_count_match", "结构、比例与数量一致"], ["logo_text_and_personalization_match", "Logo、文字与个性化信息一致"], ["thumbnail_readable", "缩略图清楚且未关键裁切"]].map(([key, label]) => <label className="flex items-center gap-2" key={key}><input checked={checks[key as keyof typeof checks]} onChange={(event) => setChecks((current) => ({ ...current, [key]: event.target.checked }))} type="checkbox" />{label}</label>)}</div><select className="form-input mt-3" value={risk} onChange={(event) => setRisk(event.target.value)}><option value="clear">合规无风险</option><option value="medium">中风险（填写理由）</option><option value="high">高风险（阻断）</option></select><textarea className="form-input mt-2 min-h-20" minLength={10} required value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="检查说明，至少 10 个字" />{risk === "medium" && <textarea className="form-input mt-2 min-h-20" minLength={10} required value={mediumReason} onChange={(event) => setMediumReason(event.target.value)} placeholder="中风险保留理由" />}<button className="button-secondary mt-2" disabled={busy} type="submit">保存检查记录</button>{error && <p className="notice-error mt-2">{error}</p>}</form>;
}
