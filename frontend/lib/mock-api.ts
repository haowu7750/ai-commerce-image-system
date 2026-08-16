import type { TaskStatus } from "@/lib/image-workflow";

export type SceneProposal = {
  id: string;
  title: string;
  situation: string;
  productRole: string;
  fidelityRule: string;
};

export type ComplianceResult = {
  status: "passed" | "blocked";
  risks: string[];
  note: string;
};

export type MockGenerationTask = {
  id: string;
  status: Exclude<TaskStatus, "idle">;
  provider: "mock-image-provider";
  outputNote: string;
};

const sceneProposals: SceneProposal[] = [
  {
    id: "scene-fridge",
    title: "晚间备餐后的冰箱整理",
    situation: "家庭厨房，整理次日早餐食材，冷白自然光。",
    productRole: "收纳盒位于冰箱中层，装入洗净水果，体现真实容量。",
    fidelityRule: "保持盒体尺寸比例、透明材质、卡扣数量与参考商品一致。",
  },
  {
    id: "scene-weekend",
    title: "周末家庭采购归置",
    situation: "厨房台面与打开的冰箱形成连续使用动线。",
    productRole: "展示从清洗、沥水到分类放入收纳盒的真实过程。",
    fidelityRule: "不得添加原商品不存在的滤水层、提手或品牌标识。",
  },
  {
    id: "scene-small-home",
    title: "小户型冰箱空间优化",
    situation: "紧凑型冰箱，使用日常蔬果和饮品建立尺度参照。",
    productRole: "突出堆叠秩序，但不夸大单盒容量或承重。",
    fidelityRule: "商品主体必须清楚可辨，禁止改变透明度与开合结构。",
  },
];

const highRiskTerms = ["永久保鲜", "绝对抗菌", "零甲醛", "行业第一"];

export const mockImageApi = {
  async listSceneProposals(): Promise<SceneProposal[]> {
    return Promise.resolve(sceneProposals);
  },

  async checkPrompt(prompt: string): Promise<ComplianceResult> {
    const risks = highRiskTerms.filter((term) => prompt.includes(term));
    if (risks.length > 0) {
      return {
        status: "blocked",
        risks,
        note: "Mock 词库命中高风险表达，禁止确认提示词。",
      };
    }

    return {
      status: "passed",
      risks: [],
      note: "仅通过本地 Mock 词库演示，不代表平台合规结论。",
    };
  },

  async createGenerationTask(): Promise<MockGenerationTask> {
    return Promise.resolve({
      id: "mock-image-task-001",
      status: "queued",
      provider: "mock-image-provider",
      outputNote: "不会调用真实模型，也不会产出真实图片。",
    });
  },

  async advanceTask(
    task: MockGenerationTask,
  ): Promise<MockGenerationTask> {
    const nextStatus = task.status === "queued" ? "running" : "succeeded";
    return Promise.resolve({
      ...task,
      status: nextStatus,
    });
  },
};
