"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AccessGate } from "@/components/access-gate";
import {
  apiRequest,
  type Asset,
  type ImageJob,
  type ImageWorkflow,
  type Project,
  type ProjectDetail,
} from "@/lib/api";

const stages = [
  ["product_type_ready", "1. 识别商品类型"],
  ["scene_plan_ready", "2. 规划真实场景"],
  ["hero_scene_selected", "3. 选择主场景"],
  ["prompt_ready", "4. 审批保真 Prompt"],
  ["candidate_ready", "5. 生成候选图"],
  ["awaiting_operator_confirmation", "6. 质检与合规"],
  ["operator_confirmed", "7. 运营最终确认"],
] as const;

const stageIndex: Record<string, number> = {
  draft: 0,
  product_type_ready: 1,
  scene_plan_ready: 2,
  hero_scene_selected: 3,
  prompt_ready: 4,
  generating: 4,
  candidate_ready: 5,
  qa_pending: 5,
  qa_failed: 5,
  compliance_blocked: 5,
  awaiting_operator_confirmation: 6,
  operator_confirmed: 7,
};

export default function ImageStudioPage() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [workflow, setWorkflow] = useState<ImageWorkflow | null>(null);
  const [job, setJob] = useState<ImageJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [manualChecks, setManualChecks] = useState({
    product_facts_match: false,
    geometry_and_count_match: false,
    logo_text_and_personalization_match: false,
    thumbnail_readable: false,
  });
  const [manualRisk, setManualRisk] = useState("clear");
  const [manualNotes, setManualNotes] = useState("");
  const [runtime, setRuntime] = useState<{
    provider: string;
    model: string;
    configured: boolean;
    paid_requests_enabled: boolean;
  } | null>(null);

  const loadProject = useCallback(async (id: string) => {
    if (!id) return;
    try {
      const [nextDetail, workflows] = await Promise.all([
        apiRequest<ProjectDetail>(`/projects/${id}`),
        apiRequest<ImageWorkflow[]>(`/image-workflows?project_id=${encodeURIComponent(id)}`),
      ]);
      setDetail(nextDetail);
      const latestWorkflow = workflows[0] ?? null;
      setWorkflow(latestWorkflow);
      if (latestWorkflow) {
        const jobs = await apiRequest<ImageJob[]>(`/image-generations?workflow_id=${encodeURIComponent(latestWorkflow.id)}`);
        setJob(jobs[0] ?? null);
      } else {
        setJob(null);
      }
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "生图项目加载失败");
    }
  }, []);

  useEffect(() => {
    apiRequest<{
      provider: string;
      model: string;
      configured: boolean;
      paid_requests_enabled: boolean;
    }>("/config/image-runtime")
      .then(setRuntime)
      .catch(() => setRuntime(null));
    apiRequest<Project[]>("/projects")
      .then((data) => {
        setProjects(data);
        const fromQuery = new URLSearchParams(window.location.search).get("project");
        const initial = data.some((item) => item.id === fromQuery) ? String(fromQuery) : (data[0]?.id ?? "");
        setProjectId(initial);
      })
      .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : "项目加载失败"));
  }, []);

  useEffect(() => { void loadProject(projectId); }, [loadProject, projectId]);

  const referenceAssets = useMemo(
    () => {
      const all = detail?.assets.filter(
        (asset) => asset.asset_type === "product_reference" && asset.file_hash,
      ) ?? [];
      const explicitlySelected = all.filter(
        (asset) => asset.metadata?.selected_for_generation === true,
      );
      return explicitlySelected.length > 0 ? explicitlySelected : all;
    },
    [detail],
  );
  const cardReady = Boolean(detail?.product_card?.confirmed_at);
  const referencesReady = referenceAssets.length > 0;
  const progress = workflow ? (stageIndex[workflow.status] ?? 0) : 0;

  async function createWorkflow() {
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await apiRequest<ImageWorkflow>("/image-workflows", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId }),
      });
      setWorkflow(created);
      setMessage("生图流程已创建，所有阶段将持久保存。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "流程创建失败");
    } finally { setBusy(false); }
  }

  async function transition(target: string, field: string, value: unknown) {
    if (!workflow) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const updated = await apiRequest<ImageWorkflow>(`/image-workflows/${workflow.id}/transition`, {
        method: "PATCH",
        body: JSON.stringify({
          expected_status: workflow.status,
          expected_revision: workflow.revision,
          target_status: target,
          [field]: value,
        }),
      });
      setWorkflow(updated);
      setMessage("阶段已保存，可继续下一步。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "阶段提交失败");
    } finally { setBusy(false); }
  }

  async function generate() {
    if (!workflow) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const created = await apiRequest<ImageJob>("/image-generations", {
        method: "POST",
        body: JSON.stringify({
          workflow_id: workflow.id,
          reference_asset_ids: referenceAssets.map((asset: Asset) => asset.id),
          n: 1,
          size: "1024x1024",
          idempotency_key: crypto.randomUUID(),
        }),
      });
      setJob(created);
      await loadProject(projectId);
      setJob(created);
      setMessage(created.provider === "mock" ? "Mock 候选图已生成（未产生付费调用）。" : "候选图已生成。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "候选图生成失败");
    } finally { setBusy(false); }
  }

  async function runChecks(scenario: string) {
    if (!workflow) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const updated = await apiRequest<ImageWorkflow>(`/image-workflows/${workflow.id}/mock-checks`, {
        method: "POST",
        body: JSON.stringify({ expected_revision: workflow.revision, scenario }),
      });
      setWorkflow(updated);
      setMessage("确定性 Mock 质检已完成；报告明确标注为非真实视觉评估。");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "质检失败");
    } finally { setBusy(false); }
  }

  async function submitManualReview(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workflow) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const updated = await apiRequest<ImageWorkflow>(`/image-workflows/${workflow.id}/manual-review`, {
        method: "POST",
        body: JSON.stringify({
          expected_revision: workflow.revision,
          ...manualChecks,
          compliance_risk: manualRisk,
          notes: manualNotes,
        }),
      });
      setWorkflow(updated);
      setMessage("运营人工真实性、缩略图和合规初审已留痕。 ");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "人工验收保存失败");
    } finally { setBusy(false); }
  }

  async function resolveRisk(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workflow) return;
    const reason = new FormData(event.currentTarget).get("reason");
    setBusy(true); setError("");
    try {
      const updated = await apiRequest<ImageWorkflow>(`/image-workflows/${workflow.id}/resolve-medium-risk`, {
        method: "POST",
        body: JSON.stringify({ expected_revision: workflow.revision, reason }),
      });
      setWorkflow(updated); setMessage("中风险处理理由已留痕，进入运营确认门禁。");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "风险处理失败"); }
    finally { setBusy(false); }
  }

  async function confirm() {
    if (!workflow) return;
    setBusy(true); setError("");
    try {
      const updated = await apiRequest<ImageWorkflow>(`/image-workflows/${workflow.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ expected_revision: workflow.revision }),
      });
      setWorkflow(updated); setMessage("候选图已由运营最终确认；系统未自动发布、未写回 ERP。");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "确认失败"); }
    finally { setBusy(false); }
  }

  return (
    <AccessGate requiredRole="operator">
      <p className="eyebrow">AI 生图工作室 · 后端状态机</p>
      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div><h1 className="text-3xl font-black">参考图保真七阶段</h1><p className="mt-2 max-w-3xl text-sm leading-6 text-stone-600">商品参考图是视觉事实源。系统只使用素材库中运营明确勾选的参考图；未勾选时回退到全部商品参考图。</p></div>
        <label className="form-label min-w-64">项目<select className="form-input" onChange={(event) => setProjectId(event.target.value)} value={projectId}><option value="">选择项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
      </div>
      {error && <p className="notice-error mt-5">{error}</p>}
      {message && <p className="notice-success mt-5">{message}</p>}
      {runtime && (
        <div className={runtime.paid_requests_enabled ? "notice-error mt-5" : "notice-success mt-5"}>
          当前生图：{runtime.provider} / {runtime.model}。
          {runtime.paid_requests_enabled
            ? " 真实付费模式已启用，只有点击“生成候选图”才会发送请求。"
            : " Mock 模式，不会产生付费请求。"}
        </div>
      )}

      {detail && <section className="mt-6 grid gap-4 md:grid-cols-2">
        <article className={`panel p-5 ${cardReady ? "border-emerald-200" : "border-amber-200"}`}><p className="text-xs font-bold text-stone-500">前置门禁 A</p><p className="mt-2 text-lg font-black">商品事实卡 {cardReady ? "已确认" : "未确认"}</p>{!cardReady && <Link className="button-secondary mt-4" href={`/projects/${projectId}`}>去确认商品事实</Link>}</article>
        <article className={`panel p-5 ${referencesReady ? "border-emerald-200" : "border-amber-200"}`}><p className="text-xs font-bold text-stone-500">前置门禁 B</p><p className="mt-2 text-lg font-black">哈希参考图 {referencesReady ? `${referenceAssets.length} 张` : "缺失"}</p>{!referencesReady && <Link className="button-secondary mt-4" href={`/projects/${projectId}`}>去上传参考图</Link>}</article>
      </section>}

      <section className="panel mt-6 p-5">
        <div className="grid gap-3 md:grid-cols-7">{stages.map(([status, label], index) => <div className={`rounded-2xl border p-3 text-xs font-bold ${progress > index ? "border-brand-500 bg-brand-50 text-brand-800" : "border-stone-200 text-stone-400"}`} key={status}>{label}</div>)}</div>
      </section>

      {!workflow && detail && <section className="panel mt-6 p-8 text-center"><h2 className="text-xl font-black">创建持久化生图流程</h2><p className="mt-2 text-sm text-stone-500">刷新页面后进度仍会保留。</p><button className="button-primary mt-5" disabled={busy || !cardReady || !referencesReady} onClick={() => void createWorkflow()} type="button">开始七阶段流程</button></section>}

      {workflow && <section className="panel mt-6 p-6">
        <div className="flex flex-wrap items-center justify-between gap-3"><div><p className="eyebrow">当前状态</p><h2 className="mt-2 text-2xl font-black">{workflow.status}</h2></div><span className="status-chip">revision {workflow.revision}</span></div>

        {workflow.status === "draft" && <StageForm title="确认商品类型" button="进入场景规划" busy={busy} defaultValue={detail?.project.category ?? "电商实物商品"} onSubmit={(value) => transition("product_type_ready", "product_type", { name: value, source: "operator_confirmed_facts" })} />}
        {workflow.status === "product_type_ready" && <StageForm title="规划真实使用场景" button="保存场景方案" busy={busy} defaultValue="真实居家使用场景，商品为视觉主体，保持结构、颜色、标识与比例一致" onSubmit={(value) => transition("scene_plan_ready", "scene_plan", { scenes: [value], fidelity: "reference_is_source_of_truth" })} />}
        {workflow.status === "scene_plan_ready" && <StageForm title="选择主场景" button="确认主场景" busy={busy} defaultValue="自然光居家主场景，商品完整清晰，背景不干扰" onSubmit={(value) => transition("hero_scene_selected", "selected_scene", { description: value, selected_by: "operator" })} />}
        {workflow.status === "hero_scene_selected" && <StageForm title="审批保真 Prompt" button="批准 Prompt" busy={busy} minLength={30} defaultValue="严格以商品参考图为视觉事实源，在真实使用场景中展示商品；不得改变结构、颜色、材质、标识、配件数量和比例，不添加商品不存在的功能或文字。" onSubmit={(value) => transition("prompt_ready", "approved_prompt", value)} />}
        {workflow.status === "prompt_ready" && <div className="mt-6 rounded-2xl bg-stone-50 p-5"><h3 className="font-black">生成候选图</h3><p className="mt-2 text-sm text-stone-600">将携带 {referenceAssets.length} 张已哈希参考图。{runtime?.paid_requests_enabled ? "点击后将调用真实模型并可能产生费用。" : "当前 Mock 模式，不收费。"}</p><button className="button-primary mt-4" disabled={busy || !runtime?.configured} onClick={() => void generate()} type="button">{runtime?.paid_requests_enabled ? "确认调用真实模型并生成 1 张" : "生成 1 张 Mock 候选图"}</button></div>}
        {workflow.status === "candidate_ready" && (
          <div className="mt-6 grid gap-5">
            <form className="rounded-2xl bg-stone-50 p-5" onSubmit={submitManualReview}>
              <h3 className="font-black">运营人工真实性与缩略图验收</h3>
              <p className="mt-2 text-sm text-stone-600">逐项查看真实候选图后勾选；系统不会把人工选择伪装成 AI 判断。</p>
              <div className="mt-4 grid gap-2">
                {([
                  ["product_facts_match", "商品颜色、材质、比例与参考图一致"],
                  ["geometry_and_count_match", "几何结构、配件与数量未改变"],
                  ["logo_text_and_personalization_match", "Logo、文字和个性化信息未改变"],
                  ["thumbnail_readable", "缩略图下商品主体仍清晰可识别"],
                ] as const).map(([key, label]) => (
                  <label className="flex items-start gap-3 rounded-xl bg-white p-3 text-sm" key={key}>
                    <input
                      checked={manualChecks[key]}
                      className="mt-1"
                      onChange={(event) => setManualChecks((current) => ({ ...current, [key]: event.target.checked }))}
                      type="checkbox"
                    />
                    {label}
                  </label>
                ))}
              </div>
              <label className="form-label mt-4">合规初审风险
                <select className="form-input" onChange={(event) => setManualRisk(event.target.value)} value={manualRisk}>
                  <option value="clear">未发现风险</option>
                  <option value="medium">中风险，需记录处理理由</option>
                  <option value="high">高风险，必须阻断</option>
                </select>
              </label>
              <label className="form-label mt-4">人工验收说明
                <textarea className="form-input" minLength={10} onChange={(event) => setManualNotes(event.target.value)} required rows={3} value={manualNotes} />
              </label>
              <button className="button-primary mt-4" disabled={busy} type="submit">保存人工验收结果</button>
            </form>
            {!runtime?.paid_requests_enabled && (
              <details className="rounded-2xl border border-stone-200 p-5">
                <summary className="cursor-pointer font-black">开发测试：Mock 门禁场景</summary>
                <p className="mt-2 text-sm text-stone-600">仅用于验证状态机，不代表视觉或法律判断。</p>
                <div className="mt-4 flex flex-wrap gap-3"><button className="button-secondary" disabled={busy} onClick={() => void runChecks("clear")} type="button">Mock 通过</button><button className="button-secondary" disabled={busy} onClick={() => void runChecks("medium_risk")} type="button">Mock 中风险</button><button className="button-secondary" disabled={busy} onClick={() => void runChecks("high_risk")} type="button">Mock 高风险</button><button className="button-secondary" disabled={busy} onClick={() => void runChecks("qa_failed")} type="button">Mock 质检失败</button></div>
              </details>
            )}
          </div>
        )}
        {workflow.status === "compliance_blocked" && workflow.compliance_status === "medium_open" && <form className="mt-6 grid gap-3 rounded-2xl bg-amber-50 p-5" onSubmit={resolveRisk}><h3 className="font-black text-amber-900">中风险需要运营说明</h3><textarea className="form-input" minLength={10} name="reason" required rows={3} /><button className="button-primary" disabled={busy} type="submit">记录理由并继续</button></form>}
        {workflow.status === "compliance_blocked" && workflow.compliance_status === "high_open" && <div className="notice-error mt-6">高风险已阻断最终确认。当前流程不能绕过，需要重新生成安全方案。</div>}
        {workflow.status === "qa_failed" && <div className="notice-error mt-6">真实性或缩略图检查失败，不能进入最终确认。请新建流程重新生成。</div>}
        {workflow.status === "awaiting_operator_confirmation" && <div className="mt-6 rounded-2xl bg-emerald-50 p-5"><h3 className="font-black text-emerald-900">全部门禁已满足</h3><p className="mt-2 text-sm text-emerald-800">只有运营角色可以执行最后确认。</p><button className="button-primary mt-4" disabled={busy} onClick={() => void confirm()} type="button">运营最终确认</button></div>}
        {workflow.status === "operator_confirmed" && <div className="notice-success mt-6">该候选图已由运营确认。没有自动发布，也没有 ERP 写回副作用。</div>}

        {job && job.outputs.map((output) => output.b64_json && <figure className="mt-6" key={output.id}><img alt="AI 候选商品场景图" className="max-h-[520px] w-full rounded-2xl border object-contain" src={`data:${output.mime_type ?? "image/png"};base64,${output.b64_json}`} /><figcaption className="mt-2 text-xs text-stone-500">{job.provider} · {job.model} · 候选 {output.sequence_no}</figcaption></figure>)}
        <details className="mt-6 rounded-2xl border border-stone-200 p-4"><summary className="cursor-pointer text-sm font-bold">查看阶段数据与报告</summary><pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(workflow, null, 2)}</pre></details>
      </section>}
    </AccessGate>
  );
}

function StageForm({ title, button, defaultValue, busy, minLength = 2, onSubmit }: { title: string; button: string; defaultValue: string; busy: boolean; minLength?: number; onSubmit: (value: string) => void | Promise<void> }) {
  return <form className="mt-6 grid gap-3 rounded-2xl bg-stone-50 p-5" onSubmit={(event) => { event.preventDefault(); void onSubmit(String(new FormData(event.currentTarget).get("value"))); }}><label className="form-label">{title}<textarea className="form-input" defaultValue={defaultValue} minLength={minLength} name="value" required rows={4} /></label><button className="button-primary" disabled={busy} type="submit">{button}</button></form>;
}
