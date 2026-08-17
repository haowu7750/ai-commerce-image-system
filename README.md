# AI 电商运营助手系统

面向拼多多商品运营的本地 MVP。系统以商品信息卡和产品参考图为事实源，覆盖图片分析、标题与 SKU、合规、美工协作、商品图/场景图生成、运营监督式批量改图、版本追踪、结果导出和 Mock ERP 写回预览。

## 当前安全口径

- 角色仅有运营、美工、管理员；管理员不自动获得业务确认权。
- 图片 Provider 默认是 `mock`，日常启动和全部自动化测试均不访问付费模型。
- 真实 Shulicode 只有在当前进程显式设置 `APP_IMAGE_PROVIDER=shulicode` 后才可能启用。
- 中转站图像模型固定为 `gpt-image-2`，不可选择或回退到其他模型。
- 文本与视觉分析在当前阶段始终使用 Mock。
- AI 候选不会自动最终化、发布或写回 ERP；高风险内容禁止确认。
- 批量改图不提供定时无人值守执行；一次最多 10 张，每张候选都必须由运营逐项检查和确认。
- 根目录 `.env.local` 可由后端配置安全读取，但不会被启动/测试脚本直接读取或打印；即使文件中存在凭证，真实 Provider 仍须显式设置 `APP_IMAGE_PROVIDER=shulicode` 才会启用。
- 脚本不会安装或更新依赖。

## 目录

- `frontend/`：Next.js + TypeScript 前端。
- `backend/`：FastAPI 后端、数据库、权限和 Provider。
- `scripts/`：Windows PowerShell 启动、测试、运行时定位和安全检查。
- `docs/implementation/`：现行生图、状态机、Provider 与验收契约。
- `AI电商运营助手系统_需求交接包_v0.1/`：原始需求交接包，不在开发过程中修改。

## 运行要求

- Windows PowerShell 5.1 或 PowerShell 7。
- `pnpm 11.x`。
- Python 3.11+。
- 前后端依赖已由用户手工安装。

运行时定位顺序：

1. 优先使用 PATH 中可实际执行的 `pnpm` 和 `python`/`python3`。
2. Python 再尝试根目录 `.venv/Scripts/python.exe`。
3. 最后尝试 Codex bundled runtime 的已知 Python 和 pnpm 路径。
4. 找不到运行时或依赖时明确退出，不自动下载或安装。

## 第一次准备依赖

以下步骤由用户明确执行一次；项目脚本不会代为执行。

### 前端

```powershell
pnpm install --frozen-lockfile
```

### 后端

先让公共运行时解析器找到 PATH Python 或 bundled Python，再创建项目虚拟环境：

```powershell
. .\scripts\Workspace.Runtime.ps1
$python = Resolve-WorkspacePython
& $python -m venv .\.venv
& .\.venv\Scripts\python.exe -m pip install -e ".\backend[test]"
```

依赖安装完成后，激活虚拟环境可确保 PATH Python 优先命中它：

```powershell
.\.venv\Scripts\Activate.ps1
```

## 默认 Mock 启动

最简单的方式是在资源管理器中双击根目录的 `Start-System.cmd`。这是安全的
Mock 体验模式。也可以在
`cmd.exe` 的任意目录直接执行：

```bat
"D:\Codex\WorkSpace\04_电商生图系统\Start-System.cmd"
```

该入口直接使用项目自己的 Python 环境，并自动定位可用 Node.js，不依赖
`PATH`、`cd`、`Set-Location` 或全局 pnpm。PowerShell 入口也保留：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Codex\WorkSpace\04_电商生图系统\scripts\Start-Local.ps1"
```

默认行为：

- 后端：`http://127.0.0.1:8100`，健康检查为 `/health`。
- 前端：`http://127.0.0.1:3100`。
- PostgreSQL 宿主机端口：`5532`（容器内仍为 `5432`）。
- 项目端口为全局台账中的固定分配，启动器禁止静默切换端口。
- 如固定端口已由本项目的同一生图模式占用，重复启动不会创建新进程，
  而是直接复用已运行系统并打开登录页。
- 如本项目正在以另一种生图模式运行，必须先用 `Stop-System.cmd`
  停止，再启动需要的模式。
- 如固定端口由无法验证为本项目的进程占用，启动器仍会停止并报错；
  必须先核对全局端口台账，处理冲突或登记新端口后再同步修改配置。
- `APP_IMAGE_PROVIDER` 未设置时由脚本显式设为 `mock`。
- `APP_TEXT_PROVIDER` 和 `APP_VISION_PROVIDER` 由脚本显式设为 `mock`。
- 后端后台日志写入 `.run/`；脚本不会自动打印日志内容。
- 停止前端进程后，脚本会清理自己启动的后端进程。

需要停止当前项目时，可双击根目录 `Stop-System.cmd`。停止脚本只会在确认
3100/8100 的进程树命令行属于本项目后才终止进程；若端口属于其他项目会拒绝操作。

只启动一端：

```powershell
pnpm run dev:backend
pnpm run dev:frontend
```

端口如需变更，必须先更新全局台账，再由开发维护者同步修改项目配置；
日常启动不要临时传入其他端口。

## 显式启用真实 Shulicode

根目录提供了单独的真实生图入口。双击：

```text
Start-Real-Image.cmd
```

该入口不读取或显示密钥，也不会在启动时发送请求。只有运营在七阶段流程中
确认商品事实、选择参考图、审批保真 Prompt，并点击“确认调用真实模型并生成”后，
才会向 Shulicode 的 `gpt-image-2` 发出参考图编辑请求。也可以在当前终端显式选择 Provider：

```powershell
$env:APP_IMAGE_PROVIDER = "shulicode"
pnpm dev
```

Shulicode 凭证可以由后端从根 `.env.local` 的 `SHULICODE_API_KEY` 安全读取，或由组织批准的安全启动器注入。启动脚本不读取、回显或提示输入 Key；缺失凭证时后端启动校验会明确失败。不要把 Key 写入 README、源码、命令参数、聊天或提交记录。

真实模式仍有以下硬限制：

- `APP_IMAGE_MODEL` 为空时设置为 `gpt-image-2`；其他值直接拒绝。
- 文本和视觉 Provider 仍强制为 Mock。
- Provider 失败时不会回退其他模型。
- 设置 Provider 不等于集成验证成功；至少需要脱敏请求/响应摘要、输出哈希和人工视觉验收证据。

恢复默认 Mock：

```powershell
$env:APP_IMAGE_PROVIDER = "mock"
```

## 本地测试

运行安全检查、前端类型检查、前端测试和后端测试：

```powershell
pnpm test
```

附加前端生产构建：

```powershell
pnpm run test:build
```

分项运行：

```powershell
pnpm run check:safety
pnpm run typecheck:web
pnpm run test:web
pnpm run test:backend
pnpm run build:web
```

`scripts/Test-Local.ps1` 在测试进程内强制：

- `APP_IMAGE_PROVIDER=mock`
- `APP_TEXT_PROVIDER=mock`
- `APP_VISION_PROVIDER=mock`
- `APP_IMAGE_MODEL=gpt-image-2`

因此即使调用测试前的终端曾启用真实 Provider，自动化测试也不会访问真实付费服务；测试结束后恢复原进程变量。

## 安全检查内容

`pnpm run check:safety` 检查：

- 后端 Provider 默认值仍为 Mock。
- 模型默认值仍锁定 `gpt-image-2`。
- 原 V0.1 交接包仍匹配当前记录的 9 文件 SHA-256 基线。
- `scripts/*.ps1` 没有自动安装依赖的命令。
- 明确列出的源码目录中没有常见硬编码 Key/Bearer Token 形态。
- 检查器只扫描明确的源码目录和扩展名，不读取环境文件。

该扫描是基础防线，不替代 Git secret scanning、依赖漏洞扫描或生产密钥管理。

## 角色功能体验

开发环境登录页提供“运营 / 美工 / 管理员”三个体验入口。它们不是前端伪造身份：后端会创建本地演示账号、签发真实 JWT，并在每个接口重新验证角色权限。

体验时不需要输入账号密码：打开登录页后直接点击“电商运营 / 美工 / 管理员”的进入按钮即可。邮箱密码表单只用于已经由管理员创建的本地账号。

- 运营：创建项目、确认商品事实、分类上传并选择参考图、使用内容 AI、执行批量替换/同指令改图/批量改尺寸并逐图验收、派发与验收美工任务、执行生图七阶段、导出 JSON/Markdown/SKU CSV、操作本地 Mock ERP 草稿写回。
- 美工：只接收分配给自己的任务，反馈状态并提交多个文件版本。
- 管理员：管理账号角色、Prompt/合规/ERP 元数据版本和审计记录；不能绕过运营确认门禁。

项目生命周期为“新建后进入草稿箱 → 开始项目后进入进行中 → 满足商品事实、最终标题、美工任务和风险门禁后由运营标记已完成”。删除为可恢复软删除：运营可删除和恢复自己的项目，管理员可查看并紧急恢复全部已删除项目，美工无项目删除视图和权限；恢复会回到删除前状态。

体验数据默认保存在本地 SQLite。浏览器演示上传采用小文件 data URL（单文件 1.2 MB 上限），正式部署应切换对象存储。默认图片 Provider 是 Mock，不产生付费请求。正式环境必须关闭开发体验登录和 `APP_AUTO_CREATE_TABLES`，并使用 Alembic 迁移。

推荐体验顺序：运营登录 → Mock ERP 导入或新建项目 → 补充并确认商品卡 → 上传并勾选商品参考图 → 内容 AI 生成标题/SKU 草稿 → 在项目详情另存并确认最终版本 → AI 生图七阶段或进入“批量改图”处理多张图片 → 运营逐图真实性、缩略图与合规验收 → 必要时创建美工任务并切换美工账号提交 → 运营验收 → 结果汇总与导出 → Mock ERP 草稿写回预览及二次确认。

## 批量改图

运营可以从左侧“批量改图”进入，也可以在商品项目详情点击“批量改图”。当前提供：

- 批量替换商品：同一商品参考图替换到多张场景图。
- 同一指令批量改图：一条修改说明应用到多张图片。
- 批量改尺寸：统一重排到 1:1、3:2、2:3、16:9 或 9:16。

使用前必须确认商品信息卡，并选择至少一张带文件哈希的“商品参考图”。一次最多处理 10 张。任务显示逐张进度和部分失败；成功候选必须逐项勾选真实性、结构与数量、Logo/文字、缩略图，并记录合规结论。检查记录不可覆盖，高风险或检查失败的候选不能确认。ZIP 只打包运营已确认的结果。

本地开发启用了自动建表，因此更新代码后正常重启即可创建批量任务表；正式 PostgreSQL 环境需要执行 `alembic upgrade head`，迁移版本为 `0005_batch_image_tasks`。

## 常见问题

### 找到 Python，但提示缺少模块

运行时存在不代表后端依赖已安装。按“第一次准备依赖”创建根 `.venv`，激活后重试。脚本不会自动运行 pip。

### PATH 没有 Python

脚本会尝试 Codex bundled Python；当前 bundled Python 可能只提供解释器，不包含 FastAPI/pytest。它可以用于创建根 `.venv`，但仍需用户手工安装项目依赖。

### 后端启动失败

查看 `.run/backend.stderr.log`。不要把可能含环境或请求上下文的完整日志直接粘贴到公开渠道；先脱敏。

### 可以只凭命令成功声称真实生图已接通吗

不可以。Mock 测试、脚手架、HTTP 200 或一次命令成功都不是实图集成证据。真实完成状态必须同时具备实际调用、输出文件、哈希、门禁和人工视觉检查证据。
