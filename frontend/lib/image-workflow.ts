export type TaskStatus = "idle" | "queued" | "running" | "succeeded" | "failed";
export type ReviewDecision = "pending" | "accepted" | "rejected";

export const IMAGE_WORKFLOW_STAGES = [
  "产品类型分析",
  "真实场景规划",
  "主场景选择",
  "保真提示词",
  "参考图生成/编辑",
  "真实性及缩略图检查",
  "运营确认",
] as const;

export type WorkflowState = {
  factsLocked: boolean;
  referenceSelected: boolean;
  productTypeAnalyzed: boolean;
  scenesPlanned: boolean;
  mainSceneSelected: boolean;
  promptConfirmed: boolean;
  compliancePassed: boolean;
  taskStatus: TaskStatus;
  authenticityChecked: boolean;
  reviewDecision: ReviewDecision;
};

export type WorkflowGates = {
  canSelectReference: boolean;
  canAnalyzeProductType: boolean;
  canPlanScenes: boolean;
  canSelectMainScene: boolean;
  canConfirmPrompt: boolean;
  canCreateTask: boolean;
  canCheckAuthenticity: boolean;
  canReview: boolean;
};

export const initialWorkflowState: WorkflowState = {
  factsLocked: false,
  referenceSelected: false,
  productTypeAnalyzed: false,
  scenesPlanned: false,
  mainSceneSelected: false,
  promptConfirmed: false,
  compliancePassed: false,
  taskStatus: "idle",
  authenticityChecked: false,
  reviewDecision: "pending",
};

export function deriveWorkflowGates(state: WorkflowState): WorkflowGates {
  return {
    canSelectReference: state.factsLocked,
    canAnalyzeProductType: state.factsLocked && state.referenceSelected,
    canPlanScenes:
      state.factsLocked &&
      state.referenceSelected &&
      state.productTypeAnalyzed,
    canSelectMainScene:
      state.factsLocked &&
      state.referenceSelected &&
      state.productTypeAnalyzed &&
      state.scenesPlanned,
    canConfirmPrompt:
      state.factsLocked &&
      state.referenceSelected &&
      state.productTypeAnalyzed &&
      state.scenesPlanned &&
      state.mainSceneSelected,
    canCreateTask:
      state.factsLocked &&
      state.referenceSelected &&
      state.productTypeAnalyzed &&
      state.scenesPlanned &&
      state.mainSceneSelected &&
      state.promptConfirmed &&
      state.compliancePassed &&
      state.taskStatus === "idle",
    canCheckAuthenticity: state.taskStatus === "succeeded",
    canReview:
      state.taskStatus === "succeeded" && state.authenticityChecked,
  };
}

export function nextMockTaskStatus(status: TaskStatus): TaskStatus {
  if (status === "queued") return "running";
  if (status === "running") return "succeeded";
  return status;
}

export function isWorkflowAccepted(state: WorkflowState): boolean {
  return (
    state.taskStatus === "succeeded" &&
    state.authenticityChecked &&
    state.reviewDecision === "accepted"
  );
}
