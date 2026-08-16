"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import { apiRequest, type Project, type ProjectDetail } from "@/lib/api";

type Trace = {
  content_version_id: string;
  version_no: number;
  provider: string;
  model: string;
  prompt_version: string;
  rule_version: string;
  network_used: false;
};

type HistoryItem = {
  id: string;
  operation: string;
  version_no: number;
  provider: string;
  model: string;
  prompt_version: string;
  rule_version: string;
  created_at: string;
  content: Record<string, unknown>;
};

type TitleResponse = {
  trace: Trace;
  candidates: Array<{
    candidate_id: string;
    text: string;
    char_count: number;
    strategy: string;
    keywords: string[];
    risk_level: string;
    can_confirm: boolean;
    risks: Array<{ original_text: string; level: string; reason: string; suggestion: string }>;
  }>;
  excluded_terms: Array<{ term: string; reason: string }>;
  warnings: string[];
  high_risk_blocked: boolean;
};

type SkuResponse = {
  trace: Trace;
  suggestions: Array<{
    item_id: string;
    original_name: string;
    proposed_display_name: string;
    attributes: Record<string, string>;
    protected: { external_sku_id: string | null; merchant_code: string | null; price: unknown; stock: unknown };
    issues: Array<{ level: string; message: string }>;
    can_confirm: boolean;
  }>;
  protected_fields: string[];
  protected_fields_unchanged: boolean;
  can_confirm_batch: boolean;
};

type ComplianceResponse = {
  trace: Trace;
  issues: Array<{
    issue_id: string;
    original_text: string;
    start: number;
    end: number;
    level: string;
    reason: string;
    suggestion: string;
  }>;
  overall_risk: string;
  high_risk_blocked: boolean;
  can_finalize: boolean;
  disclaimer: string;
};

type AnalysisResponse = {
  trace: Trace;
  facts: Array<{ code: string; text: string; evidence: string }>;
  judgments: Array<{ code: string; text: string; evidence: string }>;
  suggestions: Array<{ code: string; text: string; evidence: string }>;
  uncertainties: Array<{ code: string; text: string; evidence: string }>;
  mock_limitations: string[];
};

function TraceBadge({ trace }: { trace: Trace }) {
  return (
    <p className="mt-3 rounded-xl bg-stone-100 px-3 py-2 text-xs text-stone-600">
      {trace.provider} · {trace.model} · Prompt {trace.prompt_version} · Rule {trace.rule_version} · V{trace.version_no}
    </p>
  );
}

export default function ContentLabPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [result, setResult] = useState<
    | { kind: "analysis"; data: AnalysisResponse }
    | { kind: "title"; data: TitleResponse }
    | { kind: "sku"; data: SkuResponse }
    | { kind: "compliance"; data: ComplianceResponse }
    | null
  >(null);
  const [keywords, setKeywords] = useState("");
  const [skuText, setSkuText] = useState("白色,500ml\n黑色,500ml");
  const [complianceText, setComplianceText] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadProject = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const [nextDetail, nextHistory] = await Promise.all([
        apiRequest<ProjectDetail>(`/projects/${id}`),
        apiRequest<HistoryItem[]>(`/content-ai/projects/${id}/history`),
      ]);
      setDetail(nextDetail);
      setHistory(nextHistory);
      setComplianceText((current) => current || nextDetail.product_card?.current_title || "");
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "内容工作台加载失败");
    }
  }, []);

  useEffect(() => {
    apiRequest<Project[]>("/projects")
      .then((data) => {
        setProjects(data);
        if (data[0]) setProjectId(data[0].id);
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "项目加载失败"));
  }, []);

  useEffect(() => { void loadProject(projectId); }, [loadProject, projectId]);

  const selectedAssetIds = useMemo(() => {
    const assets = detail?.assets ?? [];
    const selected = assets.filter((asset) => asset.selected_for_generation);
    return (selected.length ? selected : assets).slice(0, 5).map((asset) => asset.id);
  }, [detail]);

  async function execute(kind: string, action: () => Promise<void>) {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice("确定性 Mock 结果已保存为 AI 草稿，尚未成为最终业务内容。");
      await loadProject(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败");
    } finally {
      setBusy("");
    }
  }

  function runAnalysis() {
    return execute("analysis", async () => {
      const data = await apiRequest<AnalysisResponse>(`/content-ai/projects/${projectId}/image-analysis`, {
        method: "POST",
        body: JSON.stringify({ selected_asset_ids: selectedAssetIds, operator_ocr_texts: [] }),
      });
      setResult({ kind: "analysis", data });
    });
  }

  function runTitle() {
    return execute("title", async () => {
      const data = await apiRequest<TitleResponse>(`/content-ai/projects/${projectId}/title-candidates`, {
        method: "POST",
        body: JSON.stringify({
          keywords: keywords.split(/[，,\s]+/).filter(Boolean),
          required_words: [],
          forbidden_words: [],
          candidate_count: 5,
          target_length: 30,
        }),
      });
      setResult({ kind: "title", data });
    });
  }

  function runSku() {
    return execute("sku", async () => {
      const items = skuText.split("\n").map((line, index) => {
        const [color = "", spec = ""] = line.split(/[,，]/).map((item) => item.trim());
        return {
          item_id: `row-${index + 1}`,
          original_name: line.trim() || `规格 ${index + 1}`,
          attributes: { color, spec },
          external_sku_id: `protected-${index + 1}`,
          merchant_code: `merchant-${index + 1}`,
          price: 99,
          stock: 10,
        };
      });
      const data = await apiRequest<SkuResponse>(`/content-ai/projects/${projectId}/sku-suggestions`, {
        method: "POST",
        body: JSON.stringify({ items, naming_order: ["color", "spec"], separator: " / ", max_length: 40, abbreviations: {} }),
      });
      setResult({ kind: "sku", data });
    });
  }

  function runCompliance() {
    return execute("compliance", async () => {
      const data = await apiRequest<ComplianceResponse>(`/content-ai/projects/${projectId}/compliance-check`, {
        method: "POST",
        body: JSON.stringify({
          content_type: "title",
          segments: [{ segment_id: "input-1", text: complianceText }],
        }),
      });
      setResult({ kind: "compliance", data });
    });
  }

  async function saveAsBusinessVersion(contentType: "title" | "sku", content: Record<string, unknown>) {
    await execute("save", async () => {
      await apiRequest(`/projects/${projectId}/content-versions`, {
        method: "POST",
        body: JSON.stringify({ content_type: contentType, content, source_kind: "ai" }),
      });
      setNotice("已另存为待运营确认的业务版本；请到项目详情复核并选择最终版。 ");
    });
  }

  return (
    <AccessGate requiredRole="operator">
      <p className="eyebrow">阶段 4 · 内容 AI</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-black">图片分析、标题、SKU 与合规</h1>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">
            当前为确定性 Mock 内容引擎，不访问网络。所有输出仅是 AI 草稿，必须由运营另存、复核并确认最终版本。
          </p>
        </div>
        <label className="form-label min-w-64">项目
          <select className="form-input" onChange={(event) => setProjectId(event.target.value)} value={projectId}>
            <option value="">选择项目</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      </div>

      {error && <p className="notice-error mt-5">{error}</p>}
      {notice && <p className="notice-success mt-5">{notice}</p>}
      {!detail?.product_card && projectId && (
        <p className="notice-error mt-5">请先在 <Link className="underline" href={`/projects/${projectId}`}>项目详情</Link> 完成商品卡。</p>
      )}

      <section className="mt-6 grid gap-5 xl:grid-cols-2">
        <article className="panel p-6">
          <h2 className="text-xl font-black">图片结构化分析</h2>
          <p className="mt-2 text-sm text-stone-600">从本项目选定素材元数据与商品事实中拆分事实、判断、建议和未知项，不伪装为真实视觉识别。</p>
          <button className="button-primary mt-4" disabled={Boolean(busy) || selectedAssetIds.length === 0 || !detail?.product_card} onClick={() => void runAnalysis()} type="button">
            {busy === "analysis" ? "分析中…" : `分析 ${selectedAssetIds.length} 张项目素材`}
          </button>
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">多候选标题</h2>
          <label className="form-label mt-4">补充关键词
            <input className="form-input" onChange={(event) => setKeywords(event.target.value)} placeholder="收纳, 白色, 可叠放" value={keywords} />
          </label>
          <button className="button-primary mt-4" disabled={Boolean(busy) || !detail?.product_card} onClick={() => void runTitle()} type="button">{busy === "title" ? "生成中…" : "生成 5 个候选"}</button>
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">SKU 展示名批量建议</h2>
          <p className="mt-2 text-xs text-stone-500">每行“颜色,规格”。外部 SKU ID、商家编码、价格和库存只做保护快照，绝不修改。</p>
          <textarea className="form-input mt-4 min-h-28" onChange={(event) => setSkuText(event.target.value)} value={skuText} />
          <button className="button-primary mt-4" disabled={Boolean(busy) || !detail?.product_card} onClick={() => void runSku()} type="button">{busy === "sku" ? "生成中…" : "生成 SKU 建议"}</button>
        </article>

        <article className="panel p-6">
          <h2 className="text-xl font-black">逐段合规检查</h2>
          <textarea className="form-input mt-4 min-h-28" onChange={(event) => setComplianceText(event.target.value)} placeholder="粘贴待检查标题或卖点" value={complianceText} />
          <button className="button-primary mt-4" disabled={Boolean(busy) || complianceText.trim().length === 0} onClick={() => void runCompliance()} type="button">{busy === "compliance" ? "检查中…" : "运行确定性词库检查"}</button>
        </article>
      </section>

      {result?.kind === "title" && (
        <section className="panel mt-6 p-6">
          <h2 className="text-xl font-black">标题候选</h2>
          <TraceBadge trace={result.data.trace} />
          <div className="mt-5 grid gap-3">
            {result.data.candidates.map((candidate) => (
              <article className="rounded-2xl border border-stone-200 p-4" key={candidate.candidate_id}>
                <div className="flex flex-wrap items-start justify-between gap-3"><p className="font-black">{candidate.text}</p><span className="status-chip">{candidate.char_count} 字 · {candidate.risk_level}</span></div>
                <p className="mt-2 text-xs text-stone-500">策略：{candidate.strategy} · 关键词：{candidate.keywords.join("、") || "无"}</p>
                {candidate.risks.map((risk) => <p className="notice-error mt-3" key={risk.original_text}>{risk.original_text}：{risk.reason}；建议：{risk.suggestion}</p>)}
                <button className="button-secondary mt-3" disabled={!candidate.can_confirm || Boolean(busy)} onClick={() => void saveAsBusinessVersion("title", { text: candidate.text, risk_level: candidate.risk_level, source_trace_id: result.data.trace.content_version_id })} type="button">另存为待确认标题版本</button>
              </article>
            ))}
          </div>
        </section>
      )}

      {result?.kind === "sku" && (
        <section className="panel mt-6 p-6">
          <h2 className="text-xl font-black">SKU 建议</h2>
          <TraceBadge trace={result.data.trace} />
          <p className="notice-success mt-4">受保护字段未修改：{result.data.protected_fields.join("、")}</p>
          <div className="mt-4 grid gap-3">{result.data.suggestions.map((item) => <article className="rounded-2xl border border-stone-200 p-4" key={item.item_id}><p className="font-black">{item.proposed_display_name}</p><p className="mt-2 text-xs text-stone-500">原名：{item.original_name}</p>{item.issues.map((issue) => <p className="notice-error mt-2" key={issue.message}>{issue.message}</p>)}</article>)}</div>
          <button className="button-primary mt-4" disabled={!result.data.can_confirm_batch || Boolean(busy)} onClick={() => void saveAsBusinessVersion("sku", { items: result.data.suggestions.map((item) => ({ item_id: item.item_id, display_name: item.proposed_display_name, ...item.protected })), risk_level: "low", source_trace_id: result.data.trace.content_version_id })} type="button">另存为待确认 SKU 版本</button>
        </section>
      )}

      {result?.kind === "compliance" && (
        <section className="panel mt-6 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-xl font-black">合规报告</h2><span className={result.data.high_risk_blocked ? "rounded-full bg-red-100 px-3 py-1 text-xs font-black text-red-800" : "status-chip"}>{result.data.overall_risk}</span></div>
          <TraceBadge trace={result.data.trace} />
          {result.data.issues.map((issue) => <article className="mt-4 rounded-2xl border border-red-200 bg-red-50 p-4" key={issue.issue_id}><p className="font-black text-red-900">“{issue.original_text}” · {issue.level}</p><p className="mt-2 text-sm text-red-800">{issue.reason}</p><p className="mt-1 text-sm text-red-800">建议：{issue.suggestion}</p></article>)}
          {!result.data.issues.length && <p className="notice-success mt-4">确定性词库未命中；仍需运营人工复核。</p>}
          <p className="mt-4 text-xs text-stone-500">{result.data.disclaimer}</p>
        </section>
      )}

      {result?.kind === "analysis" && (
        <section className="panel mt-6 p-6">
          <h2 className="text-xl font-black">结构化图片分析</h2>
          <TraceBadge trace={result.data.trace} />
          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">{(["facts", "judgments", "suggestions", "uncertainties"] as const).map((group) => <article className="rounded-2xl bg-stone-50 p-4" key={group}><h3 className="font-black">{group}</h3><div className="mt-3 grid gap-2">{result.data[group].map((item) => <div className="rounded-xl bg-white p-3 text-sm" key={item.code}><p className="font-bold">{item.text}</p><p className="mt-1 text-xs text-stone-500">{item.evidence}</p></div>)}</div></article>)}</div>
          <p className="mt-4 text-xs text-stone-500">{result.data.mock_limitations.join("；")}</p>
        </section>
      )}

      <section className="panel mt-6 p-6">
        <h2 className="text-xl font-black">AI 草稿追溯</h2>
        <div className="mt-4 grid gap-3">{history.slice(0, 12).map((item) => <article className="rounded-xl border border-stone-200 p-3 text-xs" key={item.id}><div className="flex flex-wrap justify-between gap-2"><p className="font-black">{item.operation} · V{item.version_no}</p><p className="text-stone-500">{new Date(item.created_at).toLocaleString("zh-CN")}</p></div><p className="mt-1 text-stone-500">{item.provider} · {item.model} · {item.prompt_version} · {item.rule_version}</p></article>)}</div>
      </section>
    </AccessGate>
  );
}
