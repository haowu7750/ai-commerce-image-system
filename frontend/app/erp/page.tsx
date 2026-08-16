"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import { apiRequest, type Project } from "@/lib/api";

type Capabilities = {
  display_name: string;
  mode: "mock" | "real";
  can_import_products: boolean;
  can_write_drafts: boolean;
  can_publish: boolean;
  supports_external_version_check: boolean;
  supports_idempotency: boolean;
  notes: string[];
};

type UnifiedProduct = {
  external_id: string;
  external_version: string;
  name: string;
  brand: string | null;
  title: string | null;
  category: string | null;
  facts: Record<string, unknown>;
  skus: Array<Record<string, unknown>>;
};

type SyncRecord = {
  id: string;
  direction: string;
  operation: string;
  status: string;
  project_id: string | null;
  external_entity_id: string | null;
  external_version_before: string | null;
  external_version_after: string | null;
  error_message: string | null;
  created_at: string;
};

type ImportPreview = {
  record: SyncRecord;
  product: UnifiedProduct;
  field_mapping: Record<string, string>;
  warnings: string[];
};

type ExternalMapping = {
  id: string;
  project_id: string;
  external_entity_id: string;
  external_version: string;
};

type WritebackPreview = {
  id: string;
  project_id: string;
  expected_external_version: string;
  idempotency_key: string;
  payload_json: Record<string, unknown>;
  omitted_protected_fields_json: string[];
  compliance_snapshot_json: Record<string, unknown>;
  status: string;
  external_version_after: string | null;
};

export default function ERPPage() {
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [products, setProducts] = useState<UnifiedProduct[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [mappings, setMappings] = useState<ExternalMapping[]>([]);
  const [records, setRecords] = useState<SyncRecord[]>([]);
  const [externalId, setExternalId] = useState("");
  const [storeName, setStoreName] = useState("Mock ERP 演示店");
  const [importPreview, setImportPreview] = useState<ImportPreview | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [writebackPreview, setWritebackPreview] = useState<WritebackPreview | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextCapabilities, nextProducts, nextProjects, nextMappings, nextRecords] =
        await Promise.all([
          apiRequest<Capabilities>("/erp/capabilities"),
          apiRequest<UnifiedProduct[]>("/erp/mock/products"),
          apiRequest<Project[]>("/projects"),
          apiRequest<ExternalMapping[]>("/erp/external-mappings"),
          apiRequest<SyncRecord[]>("/erp/records?limit=30"),
        ]);
      setCapabilities(nextCapabilities);
      setProducts(nextProducts);
      setProjects(nextProjects);
      setMappings(nextMappings);
      setRecords(nextRecords);
      if (nextProducts[0]) setExternalId((current) => current || nextProducts[0].external_id);
      if (nextMappings[0]) setSelectedProjectId((current) => current || nextMappings[0].project_id);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Mock ERP 数据加载失败");
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function previewImport() {
    if (!externalId || !storeName.trim()) return;
    setBusy("import-preview");
    setError("");
    setNotice("");
    try {
      const preview = await apiRequest<ImportPreview>("/erp/import-previews", {
        method: "POST",
        body: JSON.stringify({
          external_id: externalId,
          store_name: storeName.trim(),
          project_name: products.find((item) => item.external_id === externalId)?.name,
        }),
      });
      setImportPreview(preview);
      setNotice("已生成导入预览。确认后才会创建草稿项目。 ");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入预览失败");
    } finally {
      setBusy("");
    }
  }

  async function applyImport() {
    if (!importPreview) return;
    setBusy("import-apply");
    setError("");
    try {
      const applied = await apiRequest<{ project_id: string }>(
        `/erp/import-previews/${importPreview.record.id}/apply`,
        { method: "POST" },
      );
      setSelectedProjectId(applied.project_id);
      setImportPreview(null);
      setNotice("Mock ERP 商品已导入草稿箱，商品字段来源已标记为 erp:mock。 ");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "导入应用失败");
    } finally {
      setBusy("");
    }
  }

  async function previewWriteback() {
    if (!selectedProjectId) return;
    setBusy("writeback-preview");
    setError("");
    setNotice("");
    try {
      const preview = await apiRequest<WritebackPreview>(
        `/erp/projects/${selectedProjectId}/writeback-previews`,
        {
          method: "POST",
          body: JSON.stringify({ idempotency_key: crypto.randomUUID() }),
        },
      );
      setWritebackPreview(preview);
      setNotice("草稿写回预览已生成。请核对内容后由运营再次确认。 ");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "写回预览失败");
    } finally {
      setBusy("");
    }
  }

  async function confirmWriteback() {
    if (!writebackPreview) return;
    if (!window.confirm("确认把预览内容写入本地 Mock ERP 草稿区吗？该动作不会发布商品。")) return;
    setBusy("writeback-confirm");
    setError("");
    try {
      const confirmed = await apiRequest<WritebackPreview>(
        `/erp/writeback-previews/${writebackPreview.id}/confirm`,
        { method: "POST", body: JSON.stringify({ confirm: true }) },
      );
      setWritebackPreview(confirmed);
      setNotice("已写入本地 Mock ERP 草稿区；没有发布，也没有修改价格、库存或商家编码。 ");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "写回被阻止");
      await load();
    } finally {
      setBusy("");
    }
  }

  async function simulateConflict() {
    const mapping = mappings.find((item) => item.project_id === selectedProjectId);
    if (!mapping) return;
    setBusy("conflict");
    setError("");
    try {
      await apiRequest(`/erp/mock/products/${mapping.external_entity_id}/simulate-version-change`, {
        method: "POST",
      });
      setNotice("已模拟外部 ERP 版本变化。旧写回预览现在会被服务端阻止。 ");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "冲突模拟失败");
    } finally {
      setBusy("");
    }
  }

  const mappedProjects = projects.filter((project) =>
    mappings.some((mapping) => mapping.project_id === project.id),
  );

  return (
    <AccessGate requiredRole="operator">
      <p className="eyebrow">阶段 7 · 本地契约验证</p>
      <h1 className="mt-2 text-3xl font-black">Mock ERP 导入与草稿写回</h1>
      <p className="mt-2 max-w-4xl text-sm leading-6 text-stone-600">
        这里只连接本地 Mock ERP，不访问任何真实厂商。写回必须经过预览、最终版本、合规、外部版本、幂等和运营二次确认检查，且永远只写草稿、不发布。
      </p>

      {error && <p className="notice-error mt-5">{error}</p>}
      {notice && <p className="notice-success mt-5">{notice}</p>}

      <section className="mt-6 grid gap-4 md:grid-cols-4">
        <article className="panel p-5"><p className="text-xs text-stone-500">连接方式</p><p className="mt-2 text-xl font-black">{capabilities?.display_name ?? "加载中"}</p></article>
        <article className="panel p-5"><p className="text-xs text-stone-500">商品导入</p><p className="mt-2 text-xl font-black">{capabilities?.can_import_products ? "可演示" : "不可用"}</p></article>
        <article className="panel p-5"><p className="text-xs text-stone-500">草稿写回</p><p className="mt-2 text-xl font-black">{capabilities?.can_write_drafts ? "人工确认" : "不可用"}</p></article>
        <article className="panel p-5"><p className="text-xs text-stone-500">自动发布</p><p className="mt-2 text-xl font-black text-red-700">{capabilities?.can_publish ? "异常开启" : "永久关闭"}</p></article>
      </section>

      <section className="mt-6 grid gap-6 xl:grid-cols-2">
        <article className="panel p-6">
          <h2 className="text-xl font-black">1. 从 Mock ERP 导入</h2>
          <p className="mt-2 text-sm text-stone-600">先预览统一字段映射，再由运营确认创建草稿项目。</p>
          <div className="mt-5 grid gap-4">
            <label className="form-label">Mock 商品
              <select className="form-input" onChange={(event) => setExternalId(event.target.value)} value={externalId}>
                {products.map((product) => <option key={product.external_id} value={product.external_id}>{product.name} · v{product.external_version}</option>)}
              </select>
            </label>
            <label className="form-label">导入目标店铺<input className="form-input" onChange={(event) => setStoreName(event.target.value)} value={storeName} /></label>
            <button className="button-primary" disabled={Boolean(busy) || !externalId} onClick={() => void previewImport()} type="button">{busy === "import-preview" ? "生成中…" : "生成导入预览"}</button>
          </div>
          {importPreview && <div className="mt-5 rounded-2xl border border-stone-200 p-4">
            <p className="font-black">{importPreview.product.name}</p>
            <p className="mt-1 text-xs text-stone-500">外部实体 {importPreview.product.external_id} · v{importPreview.product.external_version}</p>
            {importPreview.warnings.map((warning) => <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs font-bold text-amber-900" key={warning}>{warning}</p>)}
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-stone-50 p-3 text-xs">{JSON.stringify(importPreview.product, null, 2)}</pre>
            <button className="button-primary mt-4" disabled={Boolean(busy)} onClick={() => void applyImport()} type="button">{busy === "import-apply" ? "导入中…" : "运营确认导入草稿箱"}</button>
          </div>}
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">2. 写回 Mock 草稿区</h2>
          <p className="mt-2 text-sm text-stone-600">项目需要已确认商品卡，以及标题、SKU、合规三个最终版本。</p>
          <label className="form-label mt-5">已建立外部映射的项目
            <select className="form-input" onChange={(event) => { setSelectedProjectId(event.target.value); setWritebackPreview(null); }} value={selectedProjectId}>
              <option value="">选择项目</option>
              {mappedProjects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
          </label>
          {selectedProjectId && <Link className="mt-3 inline-block text-sm font-bold text-emerald-800 underline" href={`/projects/${selectedProjectId}`}>打开项目补齐并确认内容</Link>}
          <div className="mt-4 flex flex-wrap gap-3">
            <button className="button-primary" disabled={Boolean(busy) || !selectedProjectId} onClick={() => void previewWriteback()} type="button">{busy === "writeback-preview" ? "检查中…" : "生成草稿写回预览"}</button>
            <button className="button-secondary" disabled={Boolean(busy) || !selectedProjectId} onClick={() => void simulateConflict()} type="button">模拟外部版本变化</button>
          </div>
          {writebackPreview && <div className="mt-5 rounded-2xl border border-stone-200 p-4">
            <div className="flex items-center justify-between gap-3"><p className="font-black">写回预览</p><span className="status-chip">{writebackPreview.status}</span></div>
            <p className="mt-2 text-xs text-stone-500">预期外部版本：{writebackPreview.expected_external_version} · 目标：draft</p>
            {writebackPreview.omitted_protected_fields_json.length > 0 && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-900">已自动移除受保护字段：{writebackPreview.omitted_protected_fields_json.join("、")}</p>}
            <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-stone-50 p-3 text-xs">{JSON.stringify(writebackPreview.payload_json, null, 2)}</pre>
            {writebackPreview.status === "ready" && <button className="button-primary mt-4" disabled={Boolean(busy)} onClick={() => void confirmWriteback()} type="button">{busy === "writeback-confirm" ? "写入中…" : "运营二次确认写入 Mock 草稿"}</button>}
          </div>}
        </article>
      </section>

      <section className="panel mt-6 p-6">
        <div className="flex items-center justify-between gap-3"><h2 className="text-xl font-black">同步与写回记录</h2><span className="status-chip">{records.length} 条</span></div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead><tr className="border-b text-xs text-stone-500"><th className="p-3">时间</th><th>操作</th><th>状态</th><th>外部实体</th><th>版本</th><th>错误</th></tr></thead>
            <tbody>{records.map((record) => <tr className="border-b border-stone-100" key={record.id}><td className="p-3 text-xs">{new Date(record.created_at).toLocaleString("zh-CN")}</td><td>{record.operation}</td><td>{record.status}</td><td>{record.external_entity_id ?? "—"}</td><td>{record.external_version_before ?? "—"} → {record.external_version_after ?? "—"}</td><td className="max-w-xs text-xs text-red-700">{record.error_message ?? "—"}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </AccessGate>
  );
}
