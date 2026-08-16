import { describe, expect, it } from "vitest";

import { mockImageApi } from "../lib/mock-api";

describe("Mock 生图 adapter", () => {
  it("高风险词阻断提示词确认", async () => {
    const result = await mockImageApi.checkPrompt("宣称永久保鲜的商品图片");

    expect(result.status).toBe("blocked");
    expect(result.risks).toContain("永久保鲜");
  });

  it("创建任务不会声明真实模型结果", async () => {
    const task = await mockImageApi.createGenerationTask();

    expect(task.provider).toBe("mock-image-provider");
    expect(task.status).toBe("queued");
    expect(task.outputNote).toContain("不会调用真实模型");
  });
});
