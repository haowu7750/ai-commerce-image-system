# AI 电商运营助手后端

阶段 1 FastAPI 后端骨架，包含三角色登录/RBAC、核心业务实体、审计记录、生图任务领域模型，以及 Mock/Shulicode 生图 Provider。

## 本地启动

要求 Python 3.11+。以下命令均在 `backend` 目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

`APP_AUTO_CREATE_TABLES=true` 允许本地演示在没有先运行 Alembic 时自动建表；正式环境应设为 `false` 并只使用迁移。

当 `APP_SEED_DEMO_DATA=true` 且设置了 `APP_DEMO_PASSWORD` 时，启动会创建三个账号：

- `operator@example.local`：运营
- `designer@example.local`：美工
- `admin@example.local`：管理员

三个账号使用环境变量中的同一个本地演示密码。代码、日志和安全配置接口均不会回显该密码。

## API

- `GET /health`：公开存活检查。
- `GET /api/v1/config/safe`：管理员可查看的安全配置摘要，不返回密钥、令牌或完整数据库 URL。
- `POST /api/v1/auth/login`、`GET /api/v1/auth/me`：登录与当前用户。
- `GET/POST /api/v1/admin/users`：管理员用户管理。
- `GET/POST /api/v1/projects`：运营项目最小接口。
- `POST /api/v1/image-workflows` 与状态转换接口：按商品类型、场景方案、选定场景、Prompt 审批推进工作流。
- `POST /api/v1/image-generations`：仅在工作流为 `prompt_ready`、商品卡已确认且至少引用一张带文件哈希的 `PRODUCT_REFERENCE` 时执行；默认只调用确定性的 Mock Provider。
- `GET /api/v1/image-generations/{job_id}`：查询生图任务。
- `POST /api/v1/image-workflows/{id}/mock-checks`：发布明确标记为 Mock 的真实性、缩略图与合规报告。
- `POST /api/v1/image-workflows/{id}/resolve-medium-risk`：只允许运营对中风险记录保留理由；`high_open` 没有豁免路径。
- `POST /api/v1/image-workflows/{id}/confirm`：在同一事务内重检 QA、合规、商品卡、参考图和模型；确认不会产生发布、ERP 写回或其他内容最终化副作用。

## 生图 Provider

配置按以下优先级读取：进程环境变量 > `backend/.env` > 工作区根 `.env.local`。根文件兼容 `SHULICODE_BASE_URL`、`SHULICODE_API_KEY`、`SHULICODE_IMAGE_MODEL`；`backend/.env` 和进程环境可使用对应的 `APP_IMAGE_API_BASE_URL`、`APP_IMAGE_API_KEY`、`APP_IMAGE_MODEL` 覆盖。

默认 `APP_IMAGE_PROVIDER=mock`，即使读取到 Shulicode Key 也不会访问网络。Shulicode Provider 使用 New API 兼容接口：

- `POST /images/generations`（JSON）
- `POST /images/edits`（multipart）

Shulicode Provider 只允许已验证的 `gpt-image-2`，响应兼容 `data[].b64_json` 和 `data[].url`。只有显式设置 `APP_IMAGE_PROVIDER=shulicode` 且提供 Key 后，业务接口才会发起真实请求。配置测试使用临时 env 文件，Provider 测试使用 `httpx.MockTransport`；均不会读取真实根 `.env.local`、输出密钥或访问付费服务。

## 测试

```powershell
pytest -q
```
