import { describe, expect, it } from "vitest";

import {
  deriveWorkflowGates,
  IMAGE_WORKFLOW_STAGES,
  initialWorkflowState,
  isWorkflowAccepted,
  nextMockTaskStatus,
} from "../lib/image-workflow";

describe("AI 生图人工门禁", () => {
  it("固定七阶段契约及顺序", () => {
    expect(IMAGE_WORKFLOW_STAGES).toEqual([
      "产品类型分析",
      "真实场景规划",
      "主场景选择",
      "保真提示词",
      "参考图生成/编辑",
      "真实性及缩略图检查",
      "运营确认",
    ]);
  });

  it("未锁定商品事实时禁止所有下游动作", () => {
    const gates = deriveWorkflowGates(initialWorkflowState);

    expect(gates.canSelectReference).toBe(false);
    expect(gates.canAnalyzeProductType).toBe(false);
    expect(gates.canCreateTask).toBe(false);
    expect(gates.canReview).toBe(false);
  });

  it("只有全部前置确认且合规通过时才能创建任务", () => {
    const gates = deriveWorkflowGates({
      ...initialWorkflowState,
      factsLocked: true,
      referenceSelected: true,
      productTypeAnalyzed: true,
      scenesPlanned: true,
      mainSceneSelected: true,
      promptConfirmed: true,
      compliancePassed: true,
    });

    expect(gates.canCreateTask).toBe(true);
  });

  it("任务成功仍不等于人工验收通过", () => {
    const succeeded = {
      ...initialWorkflowState,
      taskStatus: "succeeded" as const,
    };

    expect(deriveWorkflowGates(succeeded).canCheckAuthenticity).toBe(true);
    expect(deriveWorkflowGates(succeeded).canReview).toBe(false);
    expect(isWorkflowAccepted(succeeded)).toBe(false);
    expect(
      deriveWorkflowGates({ ...succeeded, authenticityChecked: true }).canReview,
    ).toBe(true);
    expect(
      isWorkflowAccepted({
        ...succeeded,
        authenticityChecked: true,
        reviewDecision: "accepted",
      }),
    ).toBe(true);
  });

  it("Mock 任务只按显式步骤推进", () => {
    expect(nextMockTaskStatus("queued")).toBe("running");
    expect(nextMockTaskStatus("running")).toBe("succeeded");
    expect(nextMockTaskStatus("succeeded")).toBe("succeeded");
  });
});
