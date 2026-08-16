"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";

import { AccessGate } from "@/components/access-gate";
import {
  ApiError,
  apiRequest,
  fileToDataUrl,
  jsonBody,
  sha256File,
  type ContentVersion,
  type DesignTask,
  type ProductCard,
  type ProjectDetail,
  type ProjectResult,
  type User,
} from "@/lib/api";

type CardForm = {
  product_name: string;
  brand: string;
  current_title: string;
  color: string;
  material: string;
  origin: string;
  selling_points: string;
  specs: string;
  forbidden_changes: string;
};

type ProjectForm = {
  name: string;
  platform: string;
  store_name: string;
  category: string;
};

const assetTypeLabels: Record<string, string> = {
  product_raw: "商品原图",
  main_image: "当前主图",
  competitor_image: "竞品参考图",
  product_reference: "商品保真参考图",
  style_reference: "风格参考图",
};

const sourceLabels: Record<string, string> = {
  operator: "运营录入",
  reference_image: "商品参考图",
  erp: "ERP 导入",
  ai_suggestion: "AI 建议（未确认）",
};

const emptyCard: CardForm = {
  product_name: "",
  brand: "",
  current_title: "",
  color: "",
  material: "",
  origin: "",
  selling_points: "",
  specs: "",
  forbidden_changes: "",
};

function listFromLines(value: string, key: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => ({ [key]: item }));
}

function cardPayload(card: CardForm, existingSources: Record<string, string> = {}) {
  const fields: Record<string, unknown> = {
    product_name: card.product_name,
    brand: card.brand || null,
    current_title: card.current_title || null,
    facts: {
      color: card.color,
      material: card.material,
      origin: card.origin,
    },
    selling_points: listFromLines(card.selling_points, "text"),
    specs: listFromLines(card.specs, "text"),
    constraints: {
      must_not_change: card.forbidden_changes
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
    },
  };
  const sources = { ...existingSources };
  [
    "product_name",
    "brand",
    "current_title",
    "color",
    "material",
    "origin",
    "selling_points",
    "specs",
    "must_not_change",
  ].forEach((field) => {
    sources[field] ??= "operator";
  });
  return { ...fields, field_sources: sources, completeness_percent: 0 };
}

export default function ProjectDetailPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [designers, setDesigners] = useState<User[]>([]);
  const [tasks, setTasks] = useState<DesignTask[]>([]);
  const [result, setResult] = useState<ProjectResult | null>(null);
  const [card, setCard] = useState<CardForm>(emptyCard);
  const [projectForm, setProjectForm] = useState<ProjectForm>({
    name: "",
    platform: "拼多多",
    store_name: "",
    category: "",
  });
  const [assetType, setAssetType] = useState("product_reference");
  const [assetUsage, setAssetUsage] = useState("");
  const [autosaveState, setAutosaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const lastSavedCard = useRef("");
  const [contentType, setContentType] = useState("title");
  const [contentText, setContentText] = useState("");
  const [riskLevel, setRiskLevel] = useState("low");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextDetail, nextDesigners, nextTasks, nextResult] =
        await Promise.all([
          apiRequest<ProjectDetail>(`/projects/${projectId}`),
          apiRequest<User[]>("/design-tasks/designers"),
          apiRequest<DesignTask[]>("/design-tasks"),
          apiRequest<ProjectResult>(`/projects/${projectId}/result-summary`),
        ]);
      setDetail(nextDetail);
      setDesigners(nextDesigners);
      setTasks(nextTasks.filter((task) => task.project_id === projectId));
      setResult(nextResult);
      setProjectForm({
        name: nextDetail.project.name,
        platform: nextDetail.project.platform,
        store_name: nextDetail.project.store_name,
        category: nextDetail.project.category ?? "",
      });
      if (nextDetail.product_card) {
        const stored = nextDetail.product_card;
        const nextCard = {
          product_name: stored.product_name,
          brand: stored.brand ?? "",
          current_title: stored.current_title ?? "",
          color: String(stored.facts.color ?? ""),
          material: String(stored.facts.material ?? ""),
          origin: String(stored.facts.origin ?? ""),
          selling_points: stored.selling_points
            .map((item) => String(item.text ?? ""))
            .filter(Boolean)
            .join("\n"),
          specs: stored.specs
            .map((item) => String(item.text ?? item.value ?? ""))
            .filter(Boolean)
            .join("\n"),
          forbidden_changes: Array.isArray(stored.constraints.must_not_change)
            ? stored.constraints.must_not_change.join("\n")
            : "",
        };
        setCard(nextCard);
        lastSavedCard.current = JSON.stringify(
          cardPayload(nextCard, stored.field_sources),
        );
      } else {
        setCard(emptyCard);
        lastSavedCard.current = "";
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "项目详情加载失败");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (
      !detail ||
      detail.project.status === "completed" ||
      detail.project.status === "archived" ||
      !card.product_name.trim()
    ) {
      return;
    }
    const payload = cardPayload(
      card,
      detail.product_card?.field_sources ?? {},
    );
    const serialized = JSON.stringify(payload);
    if (serialized === lastSavedCard.current) return;
    const timeout = window.setTimeout(async () => {
      setAutosaveState("saving");
      try {
        const saved = await apiRequest<ProductCard>(
          `/projects/${projectId}/product-card`,
          { method: "PUT", ...jsonBody(payload) },
        );
        lastSavedCard.current = serialized;
        setDetail((current) =>
          current ? { ...current, product_card: saved } : current,
        );
        setAutosaveState("saved");
      } catch (caught) {
        setAutosaveState("error");
        setError(caught instanceof ApiError ? caught.message : "商品卡自动保存失败");
      }
    }, 900);
    return () => window.clearTimeout(timeout);
  }, [card, detail, projectId]);

  const selectedAssets = useMemo(
    () => detail?.assets.filter((asset) => asset.selected_for_generation) ?? [],
    [detail],
  );
  const selectedReferenceAssets = useMemo(
    () => selectedAssets.filter((asset) => asset.asset_type === "product_reference"),
    [selectedAssets],
  );

  function updateCard(event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) {
    setCard((current) => ({
      ...current,
      [event.target.name]: event.target.value,
    }));
  }

  async function execute(key: string, action: () => Promise<unknown>, success: string) {
    setBusy(key);
    setError("");
    setMessage("");
    try {
      await action();
      setMessage(success);
      await load();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  async function saveCard(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const payload = cardPayload(card, detail?.product_card?.field_sources ?? {});
    await execute(
      "card",
      () =>
        apiRequest(`/projects/${projectId}/product-card`, {
          method: "PUT",
          ...jsonBody(payload),
        }),
      "商品信息卡已保存；如之前确认过，本次修改会使旧生图流程失效。",
    );
  }

  async function saveProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await execute(
      "project",
      () =>
        apiRequest(`/projects/${projectId}`, {
          method: "PATCH",
          ...jsonBody({
            name: projectForm.name,
            platform: projectForm.platform,
            store_name: projectForm.store_name,
            category: projectForm.category || null,
          }),
        }),
      "项目基本信息已保存。",
    );
  }

  async function uploadAsset(event: ChangeEvent<HTMLInputElement>) {
    const input = event.currentTarget;
    const file = input.files?.[0];
    if (!file) {
      return;
    }
    if (file.size > 1_200_000) {
      setError("本地功能版单张图片请控制在 1.2MB 以内。");
      return;
    }
    await execute(
      "asset",
      async () => {
        const [fileUrl, fileHash] = await Promise.all([
          fileToDataUrl(file),
          sha256File(file),
        ]);
        return await apiRequest(`/projects/${projectId}/assets`, {
          method: "POST",
          ...jsonBody({
            asset_type: assetType,
            storage_key: `local/${fileHash}/${file.name}`,
            file_url: fileUrl,
            file_hash: fileHash,
            mime_type: file.type || "application/octet-stream",
            file_size: file.size,
            usage_note: assetUsage,
            metadata: { original_name: file.name, source: "browser_upload" },
          }),
        });
      },
      `${assetTypeLabels[assetType] ?? "素材"}已上传并记录文件哈希。`,
    );
    input.value = "";
  }

  async function toggleAssetSelection(assetId: string, selected: boolean) {
    await execute(
      `asset-select-${assetId}`,
      () =>
        apiRequest(`/projects/${projectId}/assets/${assetId}/selection`, {
          method: "PUT",
          ...jsonBody({ selected_for_generation: selected }),
        }),
      selected ? "素材已加入本次 AI 生图输入。" : "素材已从本次 AI 生图输入移除。",
    );
  }

  async function archiveAsset(assetId: string, blockers: string[]) {
    if (blockers.length) {
      setError(`该素材不能归档：${blockers.join("；")}`);
      return;
    }
    if (!window.confirm("确定归档该素材吗？归档后不会出现在当前项目素材列表中。")) return;
    await execute(
      `asset-archive-${assetId}`,
      () =>
        apiRequest(`/projects/${projectId}/assets/${assetId}/archive`, {
          method: "POST",
        }),
      "素材已归档。",
    );
  }

  async function createContent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await execute(
      "content",
      () =>
        apiRequest<ContentVersion>(`/projects/${projectId}/content-versions`, {
          method: "POST",
          ...jsonBody({
            content_type: contentType,
            content: {
              text: contentText,
              risk_level: riskLevel,
              reviewed_by: "operator",
            },
            source_kind: "human",
          }),
        }),
      "新内容版本已保存，等待运营最终确认。",
    );
    setContentText("");
  }

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const requirements = String(data.get("requirements"))
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => ({ item, acceptance: "由运营按需求验收" }));
    if (selectedAssets.length) {
      requirements.push({
        item: `关联 ${selectedAssets.length} 个已选素材：${selectedAssets.map((asset) => asset.id).join(", ")}`,
        acceptance: "仅按关联素材执行，不得擅自修改商品事实",
        asset_ids: selectedAssets.map((asset) => asset.id),
      } as { item: string; acceptance: string });
    }
    await execute(
      "task",
      () =>
        apiRequest("/design-tasks", {
          method: "POST",
          ...jsonBody({
            project_id: projectId,
            assigned_to_id: String(data.get("designer")),
            title: String(data.get("title")),
            brief: String(data.get("brief")),
            priority: String(data.get("priority")),
            requirements,
          }),
        }),
      "美工任务已创建并分配。",
    );
    form.reset();
  }

  if (!detail) {
    return (
      <AccessGate requiredRole="operator">
        <p className="text-sm font-bold text-stone-500">正在加载项目数据…</p>
        {error ? <p className="notice-error mt-4">{error}</p> : null}
      </AccessGate>
    );
  }

  const completed = detail.project.status === "completed";

  return (
    <AccessGate requiredRole="operator">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">商品项目</p>
          <h1 className="mt-2 text-3xl font-black">{detail.project.name}</h1>
          <p className="mt-2 text-sm text-stone-600">
            {detail.project.platform} · {detail.project.store_name} ·{" "}
            {detail.project.category ?? "未填写类目"}
          </p>
        </div>
        {completed ? (
          <span className="status-chip">已完成 · 只读</span>
        ) : (
          <Link
            className="button-primary"
            href={`/image-studio?project=${projectId}&assets=${encodeURIComponent(selectedAssets.map((asset) => asset.id).join(","))}`}
          >
            进入 AI 生图（已选 {selectedAssets.length}）
          </Link>
        )}
      </div>

      {message ? <p className="notice-success mt-5">{message}</p> : null}
      {error ? <p className="notice-error mt-5">{error}</p> : null}
      {completed ? <p className="notice-success mt-5">该项目已完成，当前为只读状态。如需继续修改，请在项目中心点击“重新开启”。</p> : null}

      <fieldset className="contents" disabled={completed}>
      <section className="panel mt-7 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow">项目资料</p>
            <h2 className="mt-1 text-xl font-black">基本信息</h2>
          </div>
          <span className="text-xs text-stone-500">名称、平台、店铺和类目均可维护</span>
        </div>
        <form className="mt-5 grid gap-4 md:grid-cols-2" onSubmit={saveProject}>
          <label className="form-label">
            项目名称
            <input className="form-input" onChange={(event) => setProjectForm((current) => ({ ...current, name: event.target.value }))} required value={projectForm.name} />
          </label>
          <label className="form-label">
            店铺名称
            <input className="form-input" onChange={(event) => setProjectForm((current) => ({ ...current, store_name: event.target.value }))} required value={projectForm.store_name} />
          </label>
          <label className="form-label">
            平台
            <select className="form-input" onChange={(event) => setProjectForm((current) => ({ ...current, platform: event.target.value }))} value={projectForm.platform}>
              <option>拼多多</option><option>淘宝</option><option>抖音电商</option><option>Amazon</option><option>Etsy</option>
            </select>
          </label>
          <label className="form-label">
            类目
            <input className="form-input" onChange={(event) => setProjectForm((current) => ({ ...current, category: event.target.value }))} value={projectForm.category} />
          </label>
          <div className="md:col-span-2"><button className="button-primary" disabled={busy !== ""} type="submit">{busy === "project" ? "保存中…" : "保存项目资料"}</button></div>
        </form>
      </section>

      <section className="panel mt-7 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow">商品事实</p>
            <h2 className="mt-1 text-xl font-black">商品信息卡</h2>
          </div>
          <span className="status-chip">
            {detail.product_card?.confirmed_at
              ? `已确认 · 版本 ${detail.product_card.revision}`
              : `尚未确认 · 完整度 ${detail.product_card?.completeness_percent ?? 0}%`}
          </span>
        </div>
        <form className="mt-5 grid gap-4 md:grid-cols-2" onSubmit={saveCard}>
          {[
            ["product_name", "商品名称"],
            ["brand", "品牌"],
            ["current_title", "当前标题"],
            ["color", "颜色"],
            ["material", "材质"],
            ["origin", "产地"],
          ].map(([name, label]) => (
            <label className="form-label" key={name}>
              {label}
              <input
                className="form-input"
                name={name}
                onChange={updateCard}
                required={name === "product_name"}
                value={card[name as keyof CardForm]}
              />
              <span className="mt-1 text-xs font-normal text-stone-500">
                来源：{sourceLabels[detail.product_card?.field_sources[name] ?? "operator"] ?? detail.product_card?.field_sources[name] ?? "运营录入"}
              </span>
            </label>
          ))}
          <label className="form-label">
            卖点（每行一条）
            <textarea
              className="form-input min-h-28"
              name="selling_points"
              onChange={updateCard}
              value={card.selling_points}
            />
          </label>
          <label className="form-label">
            规格（每行一条）
            <textarea
              className="form-input min-h-28"
              name="specs"
              onChange={updateCard}
              value={card.specs}
            />
          </label>
          <label className="form-label md:col-span-2">
            禁改项（每行一条）
            <textarea
              className="form-input min-h-24"
              name="forbidden_changes"
              onChange={updateCard}
              value={card.forbidden_changes}
            />
          </label>
          <div className="rounded-2xl bg-stone-50 p-4 text-sm md:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="font-bold">资料完整度：{detail.product_card?.completeness_percent ?? 0}%</p>
              <p className={autosaveState === "error" ? "text-red-700" : "text-stone-500"}>
                {autosaveState === "saving" ? "自动保存中…" : autosaveState === "saved" ? "已自动保存" : autosaveState === "error" ? "自动保存失败，请手动保存" : "修改后约 1 秒自动保存"}
              </p>
            </div>
            {detail.product_card?.missing_fields.length ? (
              <ul className="mt-3 space-y-2">
                {detail.product_card.missing_fields.map((gap) => (
                  <li className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900" key={gap.field}>
                    <strong>缺少{gap.label}</strong>：{gap.impact}；影响 {gap.required_for.join("、")}。
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-emerald-700">关键商品事实已填写完整。</p>
            )}
            {detail.product_card ? (
              <div className="mt-3 flex flex-wrap gap-2" aria-label="商品字段来源">
                {Object.entries(detail.product_card.field_sources).map(([field, source]) => (
                  <span className="rounded-full border border-stone-200 bg-white px-2.5 py-1 text-xs" key={field}>
                    {field}：{sourceLabels[source] ?? source}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-3 md:col-span-2">
            <button className="button-primary" disabled={busy !== ""} type="submit">
              {busy === "card" ? "保存中…" : "保存商品卡"}
            </button>
            <button
              className="button-secondary"
              disabled={!detail.product_card || busy !== ""}
              onClick={() =>
                execute(
                  "confirm-card",
                  () =>
                    apiRequest(`/projects/${projectId}/product-card/confirm`, {
                      method: "POST",
                    }),
                  "商品事实已由运营确认。",
                )
              }
              type="button"
            >
              确认商品事实
            </button>
          </div>
        </form>
      </section>

      <section className="panel mt-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow">素材中心</p>
            <h2 className="mt-1 text-xl font-black">商品图、主图、竞品图与参考图</h2>
          </div>
          <span className={selectedReferenceAssets.length ? "status-chip" : "rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900"}>
            AI 已选 {selectedAssets.length} 张 · 保真参考图 {selectedReferenceAssets.length} 张
          </span>
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-[180px_1fr_auto]">
          <select className="form-input" onChange={(event) => setAssetType(event.target.value)} value={assetType}>
            <option value="product_raw">商品原图</option>
            <option value="main_image">当前主图</option>
            <option value="competitor_image">竞品参考图</option>
            <option value="product_reference">商品保真参考图</option>
          </select>
          <input className="form-input" maxLength={500} onChange={(event) => setAssetUsage(event.target.value)} placeholder="用途说明，例如：正面白底图，仅用于保持外观" value={assetUsage} />
          <label className="button-secondary cursor-pointer text-center">
            {busy === "asset" ? "上传中…" : "选择图片上传"}
            <input
              accept="image/*"
              className="hidden"
              disabled={busy !== ""}
              onChange={uploadAsset}
              type="file"
            />
          </label>
        </div>
        <p className="mt-3 text-xs leading-5 text-stone-500">
          商品保真参考图是外观事实来源；竞品图只可提供场景或构图参考，不能作为本商品外观依据。单张图片上限 1.2MB。
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {detail.assets.map((asset) => (
              <article className="overflow-hidden rounded-2xl border border-stone-200 bg-white" key={asset.id}>
                {asset.file_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    alt={assetTypeLabels[asset.asset_type] ?? "项目素材"}
                    className="aspect-square w-full object-contain"
                    src={asset.file_url}
                  />
                ) : null}
                <div className="space-y-2 p-3 text-xs text-stone-500">
                  <p className="font-bold text-stone-800">{assetTypeLabels[asset.asset_type] ?? asset.asset_type}</p>
                  <p>{asset.usage_note || "未填写用途说明"}</p>
                  <p>哈希：{asset.file_hash?.slice(0, 12) ?? "无"}{asset.file_hash ? "…" : ""}</p>
                  <label className="flex items-center gap-2 font-bold text-brand-700">
                    <input
                      checked={asset.selected_for_generation}
                      disabled={busy !== ""}
                      onChange={(event) => void toggleAssetSelection(asset.id, event.target.checked)}
                      type="checkbox"
                    />
                    本次 AI 生图使用
                  </label>
                  {asset.archive_blockers.length ? (
                    <div className="rounded-lg bg-amber-50 p-2 text-amber-900">
                      无法归档：{asset.archive_blockers.join("；")}
                    </div>
                  ) : null}
                  <button
                    className="font-bold text-red-600 hover:underline disabled:text-stone-300"
                    disabled={busy !== "" || asset.archive_blockers.length > 0}
                    onClick={() => void archiveAsset(asset.id, asset.archive_blockers)}
                    type="button"
                  >
                    归档素材
                  </button>
                </div>
              </article>
            ))}
          {!detail.assets.length ? (
            <p className="text-sm text-stone-500">
              尚未上传素材。生图前必须上传并选择至少一张带哈希的商品保真参考图。
            </p>
          ) : null}
        </div>
        {selectedAssets.length > 0 && !selectedReferenceAssets.length ? (
          <p className="notice-error mt-4">当前选择中没有“商品保真参考图”，后端会阻止生图。请至少选择一张。</p>
        ) : null}
      </section>

      <section className="panel mt-6 p-6">
        <p className="eyebrow">内容版本</p>
        <h2 className="mt-1 text-xl font-black">标题、SKU 与合规结论</h2>
        <form className="mt-5 grid gap-4 md:grid-cols-[180px_1fr_160px_auto]" onSubmit={createContent}>
          <select
            className="form-input"
            onChange={(event) => setContentType(event.target.value)}
            value={contentType}
          >
            <option value="title">商品标题</option>
            <option value="sku">SKU 文案</option>
            <option value="compliance">合规结论</option>
            <option value="result_note">结果备注</option>
          </select>
          <input
            className="form-input"
            onChange={(event) => setContentText(event.target.value)}
            placeholder="输入要保存的新版本内容"
            required
            value={contentText}
          />
          <select
            className="form-input"
            onChange={(event) => setRiskLevel(event.target.value)}
            value={riskLevel}
          >
            <option value="low">低风险</option>
            <option value="medium">中风险</option>
            <option value="high">高风险</option>
          </select>
          <button className="button-primary" disabled={busy !== ""} type="submit">
            保存版本
          </button>
        </form>
        <div className="mt-5 divide-y divide-stone-100">
          {detail.content_versions.map((version) => (
            <article className="flex flex-wrap items-center justify-between gap-3 py-4" key={version.id}>
              <div>
                <p className="font-bold">
                  {version.content_type} · V{version.version_no}
                  {version.is_final ? " · 最终版" : ""}
                </p>
                <p className="mt-1 text-sm text-stone-600">
                  {String(version.content.text ?? JSON.stringify(version.content))}
                </p>
              </div>
              <button
                className="button-secondary"
                disabled={version.is_final || busy !== ""}
                onClick={() =>
                  execute(
                    `finalize-${version.id}`,
                    () =>
                      apiRequest(
                        `/projects/${projectId}/content-versions/${version.id}/finalize`,
                        { method: "POST" },
                      ),
                    "内容版本已由运营确认为最终版。",
                  )
                }
                type="button"
              >
                {version.is_final ? "已确认" : "确认最终版"}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="panel mt-6 p-6">
        <p className="eyebrow">美工协作</p>
        <h2 className="mt-1 text-xl font-black">创建并分配改图任务</h2>
        {designers.length ? (
          <form className="mt-5 grid gap-4 md:grid-cols-2" onSubmit={createTask}>
            <label className="form-label">
              分配给
              <select className="form-input" name="designer" required>
                {designers.map((designer) => (
                  <option key={designer.id} value={designer.id}>
                    {designer.display_name} · {designer.email}
                  </option>
                ))}
              </select>
            </label>
            <label className="form-label">
              优先级
              <select className="form-input" defaultValue="normal" name="priority">
                <option value="low">低</option>
                <option value="normal">普通</option>
                <option value="high">高</option>
                <option value="urgent">紧急</option>
              </select>
            </label>
            <label className="form-label md:col-span-2">
              任务标题
              <input className="form-input" name="title" required />
            </label>
            <label className="form-label md:col-span-2">
              完整需求说明
              <textarea className="form-input min-h-28" minLength={10} name="brief" required />
            </label>
            <label className="form-label md:col-span-2">
              验收项（每行一条）
              <textarea className="form-input min-h-24" name="requirements" />
            </label>
            <div className="md:col-span-2">
              <button className="button-primary" disabled={busy !== ""} type="submit">
                创建任务
              </button>
            </div>
          </form>
        ) : (
          <p className="mt-4 text-sm text-stone-500">
            当前没有可分配的美工账号。管理员创建美工账号后即可分配。
          </p>
        )}
        <div className="mt-5 divide-y divide-stone-100">
          {tasks.map((task) => (
            <article className="py-4" key={task.id}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-bold">{task.title}</p>
                  <p className="mt-1 text-sm text-stone-600">
                    {task.assigned_to_name} · {task.status} · {task.priority}
                  </p>
                </div>
                <Link className="font-bold text-brand-700" href="/tasks">
                  查看与验收
                </Link>
              </div>
            </article>
          ))}
        </div>
      </section>

      </fieldset>

      <section className="panel mt-6 p-6">
        <p className="eyebrow">结果门禁</p>
        <h2 className="mt-1 text-xl font-black">项目结果摘要</h2>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-2xl bg-stone-50 p-4">
            <p className="text-xs font-bold text-stone-500">商品事实</p>
            <p className="mt-2 font-black">
              {result?.product_card_confirmed ? "已确认" : "待确认"}
            </p>
          </div>
          <div className="rounded-2xl bg-stone-50 p-4">
            <p className="text-xs font-bold text-stone-500">美工通过</p>
            <p className="mt-2 font-black">{result?.accepted_design_count ?? 0} 个</p>
          </div>
          <div className="rounded-2xl bg-stone-50 p-4">
            <p className="text-xs font-bold text-stone-500">阻断项</p>
            <p className="mt-2 font-black">{result?.blockers.length ?? 0} 项</p>
          </div>
        </div>
        {result?.blockers.length ? (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-amber-800">
            {result.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        ) : (
          <p className="notice-success mt-4">当前已满足项目结果汇总门禁。</p>
        )}
      </section>
    </AccessGate>
  );
}
