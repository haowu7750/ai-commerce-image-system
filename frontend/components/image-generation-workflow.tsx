"use client";

import { useMemo, useState } from "react";

import { productFacts, referenceCandidates } from "@/lib/demo-data";
import {
  deriveWorkflowGates,
  initialWorkflowState,
  isWorkflowAccepted,
  type ReviewDecision,
  type WorkflowState,
} from "@/lib/image-workflow";
import {
  mockImageApi,
  type ComplianceResult,
  type MockGenerationTask,
  type SceneProposal,
} from "@/lib/mock-api";

const taskLabels = {
  idle: "尚未创建",
  queued: "排队中",
  running: "运行中",
  succeeded: "Mock 成功",
  failed: "失败",
} as const;

function GateHeader({
  number,
  title,
  subtitle,
  complete,
  blocked,
}: {
  number: number | string;
  title: string;
  subtitle: string;
  complete: boolean;
  blocked?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex gap-3">
        <span
          className={
            complete
              ? "grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-600 text-sm font-black text-white"
              : "grid h-8 w-8 shrink-0 place-items-center rounded-full bg-stone-100 text-sm font-black text-stone-500"
          }
        >
          {number}
        </span>
        <div>
          <h2 className="font-black">{title}</h2>
          <p className="mt-1 text-sm leading-6 text-stone-500">{subtitle}</p>
        </div>
      </div>
      <span
        className={
          blocked
            ? "rounded-full bg-red-50 px-3 py-1 text-xs font-bold text-red-700"
            : complete
              ? "rounded-full bg-brand-50 px-3 py-1 text-xs font-bold text-brand-700"
              : "rounded-full bg-stone-100 px-3 py-1 text-xs font-bold text-stone-500"
        }
      >
        {blocked ? "已阻断" : complete ? "门禁已通过" : "等待确认"}
      </span>
    </div>
  );
}

function updateWorkflow(
  state: WorkflowState,
  patch: Partial<WorkflowState>,
): WorkflowState {
  return { ...state, ...patch };
}

export function ImageGenerationWorkflow() {
  const [workflow, setWorkflow] = useState(initialWorkflowState);
  const [referenceId, setReferenceId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<SceneProposal[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [prompt, setPrompt] = useState("");
  const [compliance, setCompliance] = useState<ComplianceResult | null>(null);
  const [task, setTask] = useState<MockGenerationTask | null>(null);
  const [authenticityChecks, setAuthenticityChecks] = useState({
    facts: false,
    structure: false,
    thumbnail: false,
  });
  const [events, setEvents] = useState<string[]>([
    "已载入静态商品样例；尚未形成任何业务确认。",
  ]);

  const gates = deriveWorkflowGates(workflow);
  const selectedScene = useMemo(
    () => scenes.find((scene) => scene.id === sceneId) ?? null,
    [sceneId, scenes],
  );

  function addEvent(message: string) {
    const time = new Date().toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    setEvents((current) => [time + " · " + message, ...current].slice(0, 8));
  }

  function lockFacts() {
    setWorkflow((current) =>
      updateWorkflow(current, {
        factsLocked: true,
      }),
    );
    addEvent("运营演示身份确认并锁定商品事实。");
  }

  function selectReference(id: string) {
    if (!gates.canSelectReference) return;

    setReferenceId(id);
    setScenes([]);
    setSceneId(null);
    setPrompt("");
    setCompliance(null);
    setTask(null);
    setWorkflow((current) =>
      updateWorkflow(current, {
        referenceSelected: true,
        productTypeAnalyzed: false,
        scenesPlanned: false,
        mainSceneSelected: false,
        promptConfirmed: false,
        compliancePassed: false,
        taskStatus: "idle",
        authenticityChecked: false,
        reviewDecision: "pending",
      }),
    );
    setAuthenticityChecks({ facts: false, structure: false, thumbnail: false });
    addEvent("已选择参考图并保留用途说明；未复制参考商品外观。");
  }

  function analyzeProductType() {
    if (!gates.canAnalyzeProductType) return;
    setWorkflow((current) =>
      updateWorkflow(current, {
        productTypeAnalyzed: true,
        scenesPlanned: false,
        mainSceneSelected: false,
        promptConfirmed: false,
        compliancePassed: false,
        taskStatus: "idle",
        authenticityChecked: false,
        reviewDecision: "pending",
      }),
    );
    addEvent("完成产品类型分析：厨房收纳用品 / 真实储物场景。");
  }

  async function loadScenes() {
    if (!gates.canPlanScenes) return;
    const proposals = await mockImageApi.listSceneProposals();
    setScenes(proposals);
    setWorkflow((current) =>
      updateWorkflow(current, {
        scenesPlanned: true,
        mainSceneSelected: false,
      }),
    );
    addEvent("Mock adapter 返回 3 个真实使用场景方案。");
  }

  function selectScene(scene: SceneProposal) {
    const nextPrompt =
      "为透明厨房收纳盒制作真实电商使用场景图。场景：" +
      scene.situation +
      "；商品作用：" +
      scene.productRole +
      "；保真要求：" +
      scene.fidelityRule +
      "。保持盒体比例、PET 透明材质和卡扣结构，不新增商品功能，不加入品牌、夸大功效或促销文字。";

    setSceneId(scene.id);
    setPrompt(nextPrompt);
    setCompliance(null);
    setTask(null);
    setWorkflow((current) =>
      updateWorkflow(current, {
        mainSceneSelected: true,
        promptConfirmed: false,
        compliancePassed: false,
        taskStatus: "idle",
        authenticityChecked: false,
        reviewDecision: "pending",
      }),
    );
    addEvent("运营选择场景方案，系统生成可编辑提示词草稿。");
  }

  function editPrompt(value: string) {
    setPrompt(value);
    setCompliance(null);
    setWorkflow((current) =>
      updateWorkflow(current, {
        promptConfirmed: false,
        compliancePassed: false,
      }),
    );
  }

  async function confirmPrompt() {
    if (!gates.canConfirmPrompt || prompt.trim().length < 30) return;
    const result = await mockImageApi.checkPrompt(prompt);
    setCompliance(result);

    if (result.status === "blocked") {
      setWorkflow((current) =>
        updateWorkflow(current, {
          promptConfirmed: false,
          compliancePassed: false,
        }),
      );
      addEvent("Mock 合规检查命中高风险词，提示词确认被阻断。");
      return;
    }

    setWorkflow((current) =>
      updateWorkflow(current, {
        promptConfirmed: true,
        compliancePassed: true,
      }),
    );
    addEvent("运营确认提示词，Mock 合规门禁通过。");
  }

  async function createTask() {
    if (!gates.canCreateTask) return;
    const created = await mockImageApi.createGenerationTask();
    setTask(created);
    setWorkflow((current) =>
      updateWorkflow(current, {
        taskStatus: created.status,
        authenticityChecked: false,
        reviewDecision: "pending",
      }),
    );
    setAuthenticityChecks({ facts: false, structure: false, thumbnail: false });
    addEvent("创建 Mock 生图任务；未调用真实模型。");
  }

  async function advanceTask() {
    if (!task || task.status === "succeeded") return;
    const updated = await mockImageApi.advanceTask(task);
    setTask(updated);
    setWorkflow((current) =>
      updateWorkflow(current, {
        taskStatus: updated.status,
      }),
    );
    addEvent(
      updated.status === "succeeded"
        ? "Mock 任务进入成功状态，等待运营人工验收。"
        : "Mock 任务进入运行中状态。",
    );
  }

  function review(decision: Exclude<ReviewDecision, "pending">) {
    if (!gates.canReview) return;
    setWorkflow((current) =>
      updateWorkflow(current, {
        reviewDecision: decision,
      }),
    );
    addEvent(
      decision === "accepted"
        ? "运营完成演示验收；该状态不代表真实图片已生成。"
        : "运营退回 Mock 结果，未形成最终版。",
    );
  }

  function confirmAuthenticity() {
    const allChecked = Object.values(authenticityChecks).every(Boolean);
    if (!gates.canCheckAuthenticity || !allChecked) return;
    setWorkflow((current) =>
      updateWorkflow(current, {
        authenticityChecked: true,
      }),
    );
    addEvent("运营完成真实性和缩略图检查，开放最终确认门禁。");
  }

  function returnToPrompt() {
    setTask(null);
    setWorkflow((current) =>
      updateWorkflow(current, {
        promptConfirmed: false,
        compliancePassed: false,
        taskStatus: "idle",
        authenticityChecked: false,
        reviewDecision: "pending",
      }),
    );
    setAuthenticityChecks({ facts: false, structure: false, thumbnail: false });
    setCompliance(null);
    addEvent("退回提示词编辑，旧 Mock 任务记录保留在演示事件中。");
  }

  return (
    <div className="mt-7 grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="grid min-w-0 gap-5">
        <section className="panel p-5 md:p-6">
          <GateHeader
            complete={workflow.factsLocked}
            number="前置 A"
            subtitle="事实来源必须可见；下游只能使用运营确认后的信息。"
            title="确认并锁定商品事实"
          />
          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {productFacts.map((fact) => (
              <div className="rounded-2xl bg-stone-50 p-4" key={fact.label}>
                <dt className="text-xs font-bold text-stone-500">{fact.label}</dt>
                <dd className="mt-1 font-bold">{fact.value}</dd>
                <dd className="mt-2 text-[11px] text-brand-700">
                  来源：{fact.source}
                </dd>
              </div>
            ))}
          </dl>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button
              className="button-primary"
              disabled={workflow.factsLocked}
              onClick={lockFacts}
              type="button"
            >
              {workflow.factsLocked ? "商品事实已锁定" : "运营确认并锁定"}
            </button>
            <p className="text-xs text-stone-500">
              演示锁定仅保存在当前页面内，刷新后重置。
            </p>
          </div>
        </section>

        <section
          className={
            gates.canSelectReference
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={workflow.referenceSelected}
            number="前置 B"
            subtitle="参考图只说明场景与构图用途，真实商品细节仍以事实卡为准。"
            title="选择参考图及用途"
          />
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            {referenceCandidates.map((reference) => {
              const selected = referenceId === reference.id;
              const gradient =
                reference.id === "ref-kitchen"
                  ? "bg-gradient-to-br from-emerald-100 to-stone-100"
                  : "bg-gradient-to-br from-amber-100 to-orange-50";

              return (
                <button
                  className={
                    selected
                      ? "overflow-hidden rounded-2xl border-2 border-brand-500 bg-white text-left"
                      : "overflow-hidden rounded-2xl border border-stone-200 bg-white text-left transition hover:border-brand-500 disabled:cursor-not-allowed"
                  }
                  disabled={!gates.canSelectReference}
                  key={reference.id}
                  onClick={() => selectReference(reference.id)}
                  type="button"
                >
                  <span
                    className={
                      "grid h-28 place-items-center text-xs font-bold text-stone-500 " +
                      gradient
                    }
                  >
                    参考图占位 · 不含真实图片
                  </span>
                  <span className="block p-4">
                    <span className="font-black">{reference.title}</span>
                    <span className="mt-1 block text-sm leading-6 text-stone-500">
                      {reference.note}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>

        <section
          className={
            gates.canAnalyzeProductType
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={workflow.productTypeAnalyzed}
            number={1}
            subtitle="先判断商品是什么、现实用途和不可虚构的结构，再规划场景。"
            title="产品类型分析"
          />
          {workflow.productTypeAnalyzed ? (
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl bg-stone-50 p-4">
                <p className="text-xs font-bold text-stone-500">产品类型</p>
                <p className="mt-2 font-black">厨房收纳用品</p>
              </div>
              <div className="rounded-2xl bg-stone-50 p-4">
                <p className="text-xs font-bold text-stone-500">真实用途</p>
                <p className="mt-2 font-black">冰箱内分类储物</p>
              </div>
              <div className="rounded-2xl bg-stone-50 p-4">
                <p className="text-xs font-bold text-stone-500">保真重点</p>
                <p className="mt-2 font-black">透明材质与卡扣结构</p>
              </div>
            </div>
          ) : (
            <div className="mt-5 rounded-2xl border border-dashed border-stone-300 p-5 text-center">
              <p className="text-sm text-stone-500">
                使用锁定事实与参考图用途生成静态分析样例。
              </p>
              <button
                className="button-secondary mt-4"
                disabled={!gates.canAnalyzeProductType}
                onClick={analyzeProductType}
                type="button"
              >
                完成 Mock 产品类型分析
              </button>
            </div>
          )}
        </section>

        <section
          className={
            gates.canPlanScenes
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={workflow.scenesPlanned}
            number={2}
            subtitle="根据产品真实用途规划多个可发生的生活场景，不先追求视觉噱头。"
            title="真实场景规划"
          />
          <div className="mt-5 rounded-2xl border border-dashed border-stone-300 p-5 text-center">
            <p className="text-sm text-stone-500">
              {workflow.scenesPlanned
                ? "已形成 3 个结构化场景方案，下一阶段再选择主场景。"
                : "Mock adapter 只返回固定的真实使用场景样例。"}
            </p>
            <button
              className="button-secondary mt-4"
              disabled={!gates.canPlanScenes || workflow.scenesPlanned}
              onClick={loadScenes}
              type="button"
            >
              {workflow.scenesPlanned ? "场景规划已完成" : "规划 Mock 真实场景"}
            </button>
          </div>
        </section>

        <section
          className={
            gates.canSelectMainScene
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={workflow.mainSceneSelected}
            number={3}
            subtitle="运营从真实场景方案中选择一个主场景，选择结果单独留痕。"
            title="主场景选择"
          />
          {scenes.length > 0 ? (
            <div className="mt-5 grid gap-3">
              {scenes.map((scene) => (
                <button
                  className={
                    sceneId === scene.id
                      ? "rounded-2xl border-2 border-brand-500 bg-brand-50/50 p-4 text-left"
                      : "rounded-2xl border border-stone-200 bg-white p-4 text-left transition hover:border-brand-500"
                  }
                  disabled={!gates.canSelectMainScene}
                  key={scene.id}
                  onClick={() => selectScene(scene)}
                  type="button"
                >
                  <span className="font-black">{scene.title}</span>
                  <span className="mt-2 block text-sm leading-6 text-stone-600">
                    {scene.situation}
                  </span>
                  <span className="mt-2 block text-xs leading-5 text-brand-700">
                    保真：{scene.fidelityRule}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="mt-5 rounded-2xl bg-stone-50 p-4 text-sm text-stone-500">
              请先完成真实场景规划。
            </p>
          )}
        </section>

        <section
          className={
            gates.canConfirmPrompt
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            blocked={compliance?.status === "blocked"}
            complete={workflow.promptConfirmed && workflow.compliancePassed}
            number={4}
            subtitle="提示词可编辑；修改后会自动撤销既有确认与合规状态。"
            title="保真提示词"
          />
          <textarea
            className="mt-5 min-h-40 w-full rounded-2xl border border-stone-200 bg-white p-4 text-sm leading-7 outline-none transition focus:border-brand-500 disabled:bg-stone-50"
            disabled={!gates.canConfirmPrompt || workflow.taskStatus !== "idle"}
            onChange={(event) => editPrompt(event.target.value)}
            placeholder="选择场景方案后生成提示词草稿"
            value={prompt}
          />
          {selectedScene ? (
            <p className="mt-2 text-xs text-stone-500">
              当前场景：{selectedScene.title}
            </p>
          ) : null}
          {compliance ? (
            <div
              className={
                compliance.status === "blocked"
                  ? "mt-4 rounded-2xl bg-red-50 p-4 text-sm text-red-800"
                  : "mt-4 rounded-2xl bg-brand-50 p-4 text-sm text-brand-700"
              }
            >
              <p className="font-bold">
                {compliance.status === "blocked"
                  ? "Mock 合规阻断"
                  : "Mock 合规通过"}
              </p>
              <p className="mt-1 leading-6">{compliance.note}</p>
              {compliance.risks.length > 0 ? (
                <p className="mt-1">命中：{compliance.risks.join("、")}</p>
              ) : null}
            </div>
          ) : null}
          <button
            className="button-primary mt-4"
            disabled={
              !gates.canConfirmPrompt ||
              prompt.trim().length < 30 ||
              workflow.taskStatus !== "idle"
            }
            onClick={confirmPrompt}
            type="button"
          >
            {workflow.promptConfirmed ? "提示词已人工确认" : "复检并确认提示词"}
          </button>
        </section>

        <section className="panel p-5 md:p-6">
          <GateHeader
            complete={workflow.taskStatus === "succeeded"}
            number={5}
            subtitle="只创建本地 Mock 状态，不发送网络请求，也不生成真实图片。"
            title="参考图生成/编辑"
          />
          <div className="mt-5 flex flex-wrap items-center justify-between gap-4 rounded-2xl bg-[#18362b] p-5 text-white">
            <div>
              <p className="text-xs font-bold uppercase tracking-wider text-emerald-200">
                {task?.id ?? "等待创建任务"}
              </p>
              <p className="mt-2 text-xl font-black">
                {taskLabels[workflow.taskStatus]}
              </p>
              <p className="mt-1 text-xs text-emerald-50/70">
                Provider：{task?.provider ?? "mock-image-provider"}
              </p>
            </div>
            {workflow.taskStatus === "idle" ? (
              <button
                className="rounded-xl bg-white px-4 py-2.5 text-sm font-black text-[#18362b] disabled:cursor-not-allowed disabled:bg-white/20 disabled:text-white/50"
                disabled={!gates.canCreateTask}
                onClick={createTask}
                type="button"
              >
                创建 Mock 任务
              </button>
            ) : workflow.taskStatus === "queued" ||
              workflow.taskStatus === "running" ? (
              <button
                className="rounded-xl bg-white px-4 py-2.5 text-sm font-black text-[#18362b]"
                onClick={advanceTask}
                type="button"
              >
                模拟推进状态
              </button>
            ) : (
              <span className="rounded-xl border border-white/20 px-4 py-2 text-sm">
                等待人工验收
              </span>
            )}
          </div>
        </section>

        <section
          className={
            gates.canCheckAuthenticity
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={workflow.authenticityChecked}
            number={6}
            subtitle="逐项核对产品真实性、结构保真和缩略图可识别性，不能仅凭任务成功放行。"
            title="真实性及缩略图检查"
          />
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            {[1, 2].map((item) => (
              <div
                className="grid min-h-40 place-items-center rounded-2xl border border-dashed border-stone-300 bg-stone-50 p-5 text-center"
                key={item}
              >
                <div>
                  <p className="font-black">Mock 结果占位 {item}</p>
                  <p className="mt-2 text-xs leading-5 text-stone-500">
                    没有真实图片，不用于发布或设计验收。
                  </p>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-5 grid gap-3">
            <label className="flex items-start gap-3 rounded-xl bg-stone-50 p-3 text-sm">
              <input
                checked={authenticityChecks.facts}
                className="mt-1 h-4 w-4 accent-emerald-700"
                disabled={
                  !gates.canCheckAuthenticity || workflow.authenticityChecked
                }
                onChange={(event) =>
                  setAuthenticityChecks((current) => ({
                    ...current,
                    facts: event.target.checked,
                  }))
                }
                type="checkbox"
              />
              商品类型、材质、规格和真实用途与锁定事实一致
            </label>
            <label className="flex items-start gap-3 rounded-xl bg-stone-50 p-3 text-sm">
              <input
                checked={authenticityChecks.structure}
                className="mt-1 h-4 w-4 accent-emerald-700"
                disabled={
                  !gates.canCheckAuthenticity || workflow.authenticityChecked
                }
                onChange={(event) =>
                  setAuthenticityChecks((current) => ({
                    ...current,
                    structure: event.target.checked,
                  }))
                }
                type="checkbox"
              />
              未新增商品不存在的结构、功能、品牌或功效表达
            </label>
            <label className="flex items-start gap-3 rounded-xl bg-stone-50 p-3 text-sm">
              <input
                checked={authenticityChecks.thumbnail}
                className="mt-1 h-4 w-4 accent-emerald-700"
                disabled={
                  !gates.canCheckAuthenticity || workflow.authenticityChecked
                }
                onChange={(event) =>
                  setAuthenticityChecks((current) => ({
                    ...current,
                    thumbnail: event.target.checked,
                  }))
                }
                type="checkbox"
              />
              缩略图尺寸下仍能识别商品主体，核心结构未被遮挡
            </label>
          </div>
          <button
            className="button-primary mt-4"
            disabled={
              !gates.canCheckAuthenticity ||
              !Object.values(authenticityChecks).every(Boolean) ||
              workflow.authenticityChecked
            }
            onClick={confirmAuthenticity}
            type="button"
          >
            {workflow.authenticityChecked
              ? "真实性检查已确认"
              : "确认真实性与缩略图检查"}
          </button>
        </section>

        <section
          className={
            gates.canReview
              ? "panel p-5 md:p-6"
              : "panel p-5 opacity-60 md:p-6"
          }
        >
          <GateHeader
            complete={isWorkflowAccepted(workflow)}
            number={7}
            subtitle="只有完成前六阶段后，运营才能确认或退回；高风险不可放行。"
            title="运营确认"
          />
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              className="button-primary"
              disabled={!gates.canReview}
              onClick={() => review("accepted")}
              type="button"
            >
              人工验收通过 · 演示
            </button>
            <button
              className="button-secondary"
              disabled={!gates.canReview}
              onClick={() => review("rejected")}
              type="button"
            >
              退回修改
            </button>
            {workflow.reviewDecision === "rejected" ? (
              <button
                className="button-secondary"
                onClick={returnToPrompt}
                type="button"
              >
                返回提示词修改
              </button>
            ) : null}
          </div>
          {workflow.reviewDecision !== "pending" ? (
            <p
              className={
                workflow.reviewDecision === "accepted"
                  ? "mt-4 rounded-xl bg-brand-50 p-3 text-sm font-bold text-brand-700"
                  : "mt-4 rounded-xl bg-amber-50 p-3 text-sm font-bold text-amber-800"
              }
            >
              {workflow.reviewDecision === "accepted"
                ? "演示门禁已走通；仍未生成任何真实业务最终版。"
                : "结果已退回，不能进入最终内容或写回流程。"}
            </p>
          ) : null}
        </section>
      </div>

      <aside className="space-y-5 xl:sticky xl:top-6 xl:self-start">
        <section className="panel p-5">
          <p className="eyebrow">当前门禁</p>
          <div className="mt-4 grid gap-2 text-xs">
            <p className="rounded-xl bg-stone-50 px-3 py-2">
              前置 A · 商品事实锁定：{workflow.factsLocked ? "已通过" : "等待"}
            </p>
            <p className="rounded-xl bg-stone-50 px-3 py-2">
              前置 B · 参考图选择：
              {workflow.referenceSelected ? "已通过" : "等待"}
            </p>
          </div>
          <ol className="mt-4 space-y-3 text-sm">
            {[
              ["产品类型分析", workflow.productTypeAnalyzed],
              ["真实场景规划", workflow.scenesPlanned],
              ["主场景选择", workflow.mainSceneSelected],
              ["保真提示词", workflow.promptConfirmed],
              ["参考图生成/编辑", workflow.taskStatus === "succeeded"],
              ["真实性及缩略图检查", workflow.authenticityChecked],
              ["运营确认", isWorkflowAccepted(workflow)],
            ].map(([label, complete], index) => (
              <li className="flex items-center gap-3" key={String(label)}>
                <span
                  className={
                    complete
                      ? "grid h-6 w-6 place-items-center rounded-full bg-brand-600 text-xs font-black text-white"
                      : "grid h-6 w-6 place-items-center rounded-full bg-stone-100 text-xs font-black text-stone-500"
                  }
                >
                  {complete ? "✓" : index + 1}
                </span>
                <span className={complete ? "font-bold" : "text-stone-500"}>
                  {String(label)}
                </span>
              </li>
            ))}
          </ol>
        </section>

        <section className="panel p-5">
          <p className="eyebrow">演示事件</p>
          <div className="mt-4 space-y-3">
            {events.map((event, index) => (
              <p
                className="border-l-2 border-brand-100 pl-3 text-xs leading-5 text-stone-600"
                key={event + index}
              >
                {event}
              </p>
            ))}
          </div>
          <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs leading-5 text-amber-900">
            这里只展示前端事件。正式审计必须由后端保存操作人、输入快照、规则版本和结果。
          </p>
        </section>
      </aside>
    </div>
  );
}
