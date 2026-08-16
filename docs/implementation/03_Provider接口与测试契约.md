# 生图 Provider 接口与测试契约

> 文档类型：阶段 0 开发契约  
> 日期：2026-08-10  
> 关联规格：`01_MVP生图模块规格_v0.2.md`、`02_状态机与权限门禁.md`  

## 1. Provider 决策矩阵

| 能力 | MVP 运行实现 | CI/本地实现 | 外部网络 |
|---|---|---|---|
| 产品类型分析 | `MockTextProvider` + `MockVisionProvider` | 同一确定性 Mock | 禁止 |
| 真实场景规划 | `MockTextProvider` | 同一确定性 Mock | 禁止 |
| 保真 Prompt 构建/检查 | `MockTextProvider` + 确定性规则 | 同一确定性 Mock | 禁止 |
| 商品图/场景图生成与编辑 | 中转站 `RelayImageProvider`，模型固定 `gpt-image-2` | `MockImageProvider` | 仅中转站模式允许 |
| 真实性与缩略图语义检查 | `MockVisionProvider`；尺寸、格式、哈希和缩略图由本地逻辑处理 | 同一确定性 Mock | 禁止 |

| 需求编号 | 规范性要求 | 验收条件 |
|---|---|---|
| IMG-PROV-001 | 业务层只依赖内部 Provider 协议，不直接依赖中转站请求字段。 | 使用 Mock 与 Relay 适配器运行同一组契约测试，业务服务代码无中转站私有字段。 |
| IMG-PROV-002 | 中转站模型允许列表只有 `gpt-image-2`。服务端固定并复核模型，不接受客户端绕过。 | 请求 `gpt-image-1`、空值篡改或未知模型均返回 `PROVIDER_MODEL_NOT_ALLOWED`，外部调用计数为 0。 |
| IMG-PROV-003 | 不允许静默回退到其他模型或供应商；`gpt-image-2` 不可用时任务明确失败。 | 模拟模型不可用后状态为 `generation_failed`，审计中无第二模型请求。 |
| IMG-PROV-004 | 文本与视觉能力首版必须使用确定性 Mock，不调用中转站或其他外部模型。 | 断网运行所有文本/视觉契约测试通过；网络拦截器捕获请求数为 0。 |
| IMG-PROV-005 | 图像 Relay 调用与 Mock 图像调用共享同一请求、响应和错误协议。 | 替换实现无需修改工作流服务和 API Schema。 |

## 2. 内部协议

以下为语言无关接口；具体实现可以使用 Python `Protocol`/ABC。

```text
TextReasoningProvider.analyze_product_type(request) -> ProductTypeAnalysis
TextReasoningProvider.plan_real_scenes(request) -> ScenePlan
TextReasoningProvider.build_fidelity_prompt(request) -> FidelityPrompt
VisionAnalysisProvider.check_candidate(request) -> ImageQualityReport
ImageGenerationProvider.generate_or_edit(request) -> ImageProviderResult
```

### 2.1 通用调用上下文

```json
{
  "task_id": "img_task_001",
  "project_id": "project_001",
  "workflow_id": "img_workflow_001",
  "request_id": "req_001",
  "idempotency_key": "img_workflow_001:prompt_v3:attempt_root_1",
  "fact_snapshot_id": "fact_snapshot_7",
  "reference_set_version": 2,
  "actor_id": "user_001"
}
```

| 需求编号 | 请求契约 | 验收条件 |
|---|---|---|
| IMG-PROV-101 | 每次调用都包含可追溯的任务、项目、工作流、请求、幂等、事实快照和参考集版本。 | 缺任一必填字段时在适配器调用前返回 Schema 错误。 |
| IMG-PROV-102 | Provider 不从当前数据库状态隐式读取事实；所需输入全部来自不可变调用快照。 | 调用期间修改商品卡，Mock 输出仍与调用快照一致。 |
| IMG-PROV-103 | 调用上下文中的 `actor_id` 只用于审计，不用于 Provider 自行授权；授权在业务服务调用前完成。 | 直接实例化 Provider 不能推进工作流或写确认状态。 |

### 2.2 图像生成/编辑请求

```json
{
  "context": { "...": "见通用调用上下文" },
  "model": "gpt-image-2",
  "mode": "generate",
  "prompt": {
    "version_id": "prompt_v3",
    "scene_instruction": "...",
    "product_lock": ["..."],
    "negative_constraints": ["..."]
  },
  "reference_images": [
    {
      "asset_id": "asset_product_ref_1",
      "sha256": "hex-digest",
      "purpose": "product_truth"
    }
  ],
  "parent_candidate_id": null,
  "output": {
    "aspect_ratio": "1:1",
    "candidate_count": 1
  }
}
```

`mode=edit` 时 `parent_candidate_id` 必填。MVP 每个请求只生成一个候选；多个候选通过多个具有不同幂等键的任务产生。

| 需求编号 | 请求契约 | 验收条件 |
|---|---|---|
| IMG-PROV-201 | `reference_images` 至少包含一项 `purpose=product_truth`，并在调用前复核文件哈希。 | 缺失、跨项目或哈希不一致时返回稳定错误且不调用中转站。 |
| IMG-PROV-202 | `prompt` 必须同时包含场景、产品锁定项和负向约束，并引用已通过检查的 Prompt 版本。 | 三项任一为空或版本过期时请求失败。 |
| IMG-PROV-203 | `mode` 只能为 `generate` 或 `edit`；编辑必须有当前工作流内的父候选。 | 非法模式、缺父候选、跨工作流父候选均被拒绝。 |
| IMG-PROV-204 | MVP `candidate_count` 固定为 1；不允许中转站一次返回未建模的多结果。 | 值不为 1 返回字段校验错误。 |
| IMG-PROV-205 | 适配器负责把内部宽高比、参考图和 Prompt 映射为中转站协议；中转站原始字段不进入业务数据库。 | 数据库快照只含内部 Schema 与经过脱敏的响应摘要。 |

### 2.3 图像结果

```json
{
  "provider_request_id": "relay_req_123",
  "model": "gpt-image-2",
  "mode": "generate",
  "artifact": {
    "storage_key": "generated/project_001/candidate_001.png",
    "mime_type": "image/png",
    "width": 1024,
    "height": 1024,
    "byte_size": 123456,
    "sha256": "hex-digest"
  },
  "usage": { "provider_units": null },
  "created_at": "2026-08-10T00:00:00Z"
}
```

| 需求编号 | 响应契约 | 验收条件 |
|---|---|---|
| IMG-PROV-301 | 结果必须回显实际模型且严格等于 `gpt-image-2`；不一致视为无效输出。 | 伪造其他模型响应被隔离，不创建可确认候选。 |
| IMG-PROV-302 | 文件 MIME、像素尺寸、字节数和 SHA-256 由服务端读取实际文件计算，不能只信任响应元数据。 | 篡改响应元数据或文件后校验失败并删除/隔离临时输出。 |
| IMG-PROV-303 | 只有输出校验和持久化事务都成功后，任务才能标记 `succeeded`。 | 模拟存储失败时任务失败且无悬空候选记录。 |
| IMG-PROV-304 | Provider 成功结果不得包含或触发最终化、确认、发布、ERP 写回字段。 | 响应 Schema 拒绝这些字段；事件总线无对应副作用。 |

## 3. 幂等、重试与迟到结果

| 需求编号 | 规范性要求 | 验收条件 |
|---|---|---|
| IMG-PROV-401 | 幂等键在图像任务范围内唯一；相同键返回已有任务，不重复调用 Provider。 | 并发双请求的中转站调用计数为 1。 |
| IMG-PROV-402 | 仅超时、限流和暂时服务不可用可重试；鉴权、模型禁止、输入非法和安全拒绝不可自动重试。 | 错误夹具映射的 `retryable` 与错误表一致。 |
| IMG-PROV-403 | 自动重试上限为 1 次；之后必须由运营显式重试。 | 连续超时只产生初次调用和一次自动重试。 |
| IMG-PROV-404 | 工作流取消或失效后的迟到结果可存为隔离审计产物，但不能成为当前候选或被确认。 | 取消后模拟成功回调，当前候选不变且结果标记 `orphaned`。 |

## 4. 错误契约

统一错误格式：

```json
{
  "error": {
    "code": "PROVIDER_TIMEOUT",
    "message": "图像生成服务暂时超时",
    "request_id": "req_001",
    "retryable": true,
    "details": {}
  }
}
```

| 内部错误码 | 可重试 | HTTP 建议 | 触发条件 |
|---|---:|---:|---|
| `REFERENCE_IMAGE_REQUIRED` | 否 | 422 | 无产品参考图 |
| `REFERENCE_VERSION_STALE` | 否 | 409 | 参考图哈希或版本变化 |
| `PROVIDER_MODEL_NOT_ALLOWED` | 否 | 422 | 模型不是 `gpt-image-2` |
| `PROVIDER_AUTH_FAILED` | 否 | 502 | 中转站凭证无效 |
| `PROVIDER_RATE_LIMITED` | 是 | 503 | 中转站限流 |
| `PROVIDER_TIMEOUT` | 是 | 504 | 超时 |
| `PROVIDER_UNAVAILABLE` | 是 | 503 | 暂时不可用 |
| `PROVIDER_SAFETY_REJECTED` | 否 | 422 | 输入或输出被安全策略拒绝 |
| `PROVIDER_OUTPUT_INVALID` | 否 | 502 | 模型、文件或响应结构不符合契约 |
| `ARTIFACT_STORAGE_FAILED` | 是 | 503 | 文件持久化失败 |

| 需求编号 | 错误要求 | 验收条件 |
|---|---|---|
| IMG-PROV-501 | 适配器把中转站错误映射为稳定内部错误，不把原始响应、堆栈或密钥返回前端。 | 对错误表逐项运行夹具，前端响应只含统一字段。 |
| IMG-PROV-502 | 错误必须记录 `request_id` 和经过脱敏的 Provider 请求 ID。 | 用户提示和管理员日志可通过请求 ID 关联，同一日志无密钥。 |

## 5. 配置与安全

建议配置名：`IMAGE_PROVIDER_MODE=mock|relay`、`IMAGE_RELAY_BASE_URL`、`IMAGE_RELAY_TOKEN`、`IMAGE_MODEL_ALLOWLIST=gpt-image-2`。名称是内部约定，不表示可把值写入仓库。

| 需求编号 | 安全要求 | 验收条件 |
|---|---|---|
| IMG-PROV-601 | Token 仅从环境变量或安全密钥存储读取，不进入源码、数据库、请求快照、日志或前端。 | 密钥扫描与日志扫描均无明文；管理页只显示配置状态。 |
| IMG-PROV-602 | Relay 基础地址由管理员安全配置固定，业务请求不能提交任意 URL。 | 在请求体注入 URL 不改变目标地址，SSRF 测试被拒绝。 |
| IMG-PROV-603 | 参考图通过服务端对象 ID 读取，不接受业务用户提交的任意远程图片 URL。 | 内网、本地文件和未知域 URL 输入均不能绕过素材服务。 |
| IMG-PROV-604 | 上传及输出执行 MIME、扩展名、大小、像素和解码检查；临时文件失败后清理。 | 伪装扩展名、损坏文件和超限文件夹具均被隔离。 |

## 6. 契约测试清单

| 测试编号 | 覆盖需求 | 测试与通过条件 |
|---|---|---|
| T-IMG-PROV-001 | IMG-PROV-001、IMG-PROV-005 | Mock 与 Relay 测试替身通过同一协议测试，业务服务无需分支字段。 |
| T-IMG-PROV-002 | IMG-PROV-002、IMG-PROV-003 | 非 `gpt-image-2` 被拒绝；模型不可用时不回退。 |
| T-IMG-PROV-003 | IMG-PROV-004 | 文本/视觉 Mock 在禁网环境完成产品分析、场景规划、Prompt 和 QA。 |
| T-IMG-PROV-004 | IMG-PROV-201～IMG-PROV-205 | 参考图、Prompt、模式、父候选和单候选约束逐项通过正负测试。 |
| T-IMG-PROV-005 | IMG-PROV-301～IMG-PROV-304 | 错模型、损坏文件、存储失败和副作用字段均不能创建可确认候选。 |
| T-IMG-PROV-006 | IMG-PROV-401～IMG-PROV-404 | 并发幂等、重试上限、不可重试错误和迟到结果隔离均通过。 |
| T-IMG-PROV-007 | IMG-PROV-501、IMG-PROV-502 | 所有错误映射稳定且无原始敏感响应泄漏。 |
| T-IMG-PROV-008 | IMG-PROV-601～IMG-PROV-604 | 密钥、SSRF、远程 URL 和恶意文件测试全部通过。 |
| T-IMG-PROV-009 | IMG-WF-503、IMG-WF-704 | 生成成功和运营确认后，发布、ERP 写回和其他内容自动最终化事件均为 0。 |
| T-IMG-PROV-010 | IMG-DOD-002 | 若配置真实中转站，保存一次脱敏请求/响应摘要、输出哈希和人工视觉验收；无证据时测试状态只能为 `not_run`，不能写 `passed`。 |
