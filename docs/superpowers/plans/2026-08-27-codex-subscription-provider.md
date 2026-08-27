# ChatGPT Subscription Codex Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过官方 Codex app-server 将单用户 ChatGPT Plus/Pro 订阅接入 MiroFish 全部文本 LLM 调用，并在 Codex不可用时自动回退 DeepSeek。

**Architecture:** 新增仅 Docker 内网可访问的 Python `codex-gateway`，对现有代码提供 OpenAI-compatible Chat Completions 子集。Gateway 使用官方 `openai-codex==0.147.0` SDK及其固定 runtime管理 ChatGPT OAuth、thread/turn和结构化输出；本地 TEI Embedding绕过 Gateway，DeepSeek由 Gateway作为回退。

**Tech Stack:** Python 3.11、Flask、Gunicorn、openai-codex 0.147.0、OpenAI Python SDK、Docker Compose、pytest

**Spec:** `docs/superpowers/specs/2026-08-27-codex-subscription-provider-design.md`

## Global Constraints

- 单用户，不新增邀请码、本地账户或多租户数据模型。
- ChatGPT订阅为全部文本 LLM任务首选；DeepSeek保留并自动回退。
- OAuth Token只由官方 Codex runtime管理，业务代码不得读取或解析 auth.json。
- Gateway、app-server和认证接口不暴露公网，不得映射宿主机公网端口。
- Embedding继续直连 TEI，不得进入 Codex Gateway。
- Codex固定 read-only sandbox、非交互审批和一个活跃 turn。
- 技术验证成功前不得切换生产 MiroFish的 LLM Base URL。
- 未经用户明确授权不得 Git commit 或 push。

---

## File Map

- `codex_gateway/pyproject.toml`：Gateway锁定依赖与测试依赖。
- `codex_gateway/uv.lock`：可复现依赖锁。
- `codex_gateway/Dockerfile`：Gateway和官方 Codex runtime镜像。
- `codex_gateway/app/__init__.py`：Flask应用工厂与生命周期。
- `codex_gateway/app/config.py`：Codex、队列、内部 Token和 fallback配置。
- `codex_gateway/app/messages.py`：Chat Completions消息转 Codex输入。
- `codex_gateway/app/codex_provider.py`：官方 SDK包装、账户状态和 turn执行。
- `codex_gateway/app/deepseek_provider.py`：DeepSeek回退调用。
- `codex_gateway/app/router.py`：错误分类、结构化验证和回退策略。
- `codex_gateway/app/api.py`：`/health`、`/account`、`/v1/chat/completions`。
- `codex_gateway/app/login.py`：服务器终端 Device Code登录/登出工具。
- `codex_gateway/tests/**`：消息、结构化输出、回退、并发、脱敏与 API契约测试。
- `docker-compose.production.yml`：新增 Gateway服务和 auth volume。
- `.env.production.example`：新增 Gateway与 fallback非秘密配置。
- `backend/app/config.py`：允许文本 LLM指向内部 Gateway，Embedding保持独立。
- `docs/deployment/codex-subscription.md`：不含服务器 IP的通用登录、状态、回滚说明。

### Task 1: 官方 SDK Runtime 技术探针

**Files:**
- Create: `codex_gateway/pyproject.toml`
- Create: `codex_gateway/app/__init__.py`
- Create: `codex_gateway/app/probe.py`
- Create: `codex_gateway/Dockerfile`
- Create: `codex_gateway/tests/test_probe.py`

**Interfaces:**
- Produces: `probe_runtime() -> dict[str, object]`，返回 SDK版本、app-server元数据、账户是否存在和可用模型 ID；不返回 Token。

- [ ] **Step 1: 写 runtime探针失败测试**

```python
def test_probe_redacts_account_and_runtime_metadata(fake_codex):
    result = probe_runtime(codex_factory=lambda: fake_codex)
    assert result == {
        "sdk_version": "0.147.0",
        "server_name": "codex-app-server",
        "authenticated": False,
        "plan_type": None,
        "models": ["gpt-5.4"],
    }
    assert "access" not in repr(result).lower()
    assert "refresh" not in repr(result).lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd codex_gateway && uv run pytest tests/test_probe.py -v`

Expected: FAIL，因为 Gateway包和 `probe_runtime` 尚不存在。

- [ ] **Step 3: 创建锁定依赖**

`pyproject.toml` 使用 Python `>=3.11,<3.13`，运行依赖固定：

```toml
dependencies = [
  "flask>=3.1,<4",
  "gunicorn>=23,<24",
  "openai>=1.109,<2",
  "openai-codex==0.147.0",
]
```

开发依赖包含 `pytest>=8,<9`。执行 `uv lock` 生成 `uv.lock`。

- [ ] **Step 4: 实现只读探针**

使用 `Codex(config=CodexConfig(env={"CODEX_HOME": ...}))`，调用 `account(refresh_token=False)` 和 `models()`，仅返回安全元数据。必须使用 context manager关闭 runtime。

- [ ] **Step 5: 实现 Gateway Dockerfile**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app
COPY codex_gateway/pyproject.toml codex_gateway/uv.lock ./
RUN uv sync --frozen --no-dev
COPY codex_gateway/ ./
RUN install -d -m 0700 /var/lib/codex /workspace
ENV CODEX_HOME=/var/lib/codex
CMD [".venv/bin/gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8080", "app:create_app()"]
```

- [ ] **Step 6: 构建并运行未登录探针**

Run: `docker build -f codex_gateway/Dockerfile -t mirofish-codex-gateway-probe .`

Run: `docker run --rm --memory=512m -e CODEX_HOME=/tmp/codex-home mirofish-codex-gateway-probe .venv/bin/python -m app.probe`

Expected: runtime启动成功，输出 `authenticated=false` 和 SDK/app-server版本，不输出 Token；RSS小于512 MiB。

- [ ] **Step 7: 运行测试与敏感信息扫描**

Run: `cd codex_gateway && uv run pytest -v`

Run: `rg -n 'access_token|refresh_token|auth\.json' codex_gateway/app`

Expected: 测试通过；只允许注释或显式拒绝读取 auth.json的代码，不存在 Token打印。

### Task 2: 消息转换与 Codex Provider

**Files:**
- Create: `codex_gateway/app/messages.py`
- Create: `codex_gateway/app/codex_provider.py`
- Create: `codex_gateway/tests/test_messages.py`
- Create: `codex_gateway/tests/test_codex_provider.py`

**Interfaces:**
- Produces: `build_codex_input(messages: list[dict]) -> CodexInput`。
- Produces: `CodexProvider.complete(request: CompletionRequest) -> ProviderResult`。
- Produces: `CodexProvider.account_status() -> AccountStatus`。

- [ ] **Step 1: 写角色顺序失败测试**

测试 system/developer进入 instructions，user/assistant/tool按原顺序进入 turn文本；输入不得包含 API Key或内部 Gateway Token。

- [ ] **Step 2: 写 text/json_object/json_schema失败测试**

使用 fake SDK断言：

- text不传 `output_schema`。
- json_schema原样传入 `thread.run(output_schema=...)`。
- json_object追加仅返回合法 JSON的约束并完成 JSON解析。

- [ ] **Step 3: 运行测试确认因实现缺失失败**

Run: `cd codex_gateway && uv run pytest tests/test_messages.py tests/test_codex_provider.py -v`

- [ ] **Step 4: 实现消息转换**

`CodexInput`包含 `base_instructions`、`developer_instructions`、`turn_text`。消息内容用 JSON编码的角色段落构造，不使用字符串拼接生成命令行参数。

- [ ] **Step 5: 实现 Provider**

Provider复用单一官方 `Codex`实例；每次请求调用：

```python
thread = codex.thread_start(
    ephemeral=True,
    model=config.codex_model,
    base_instructions=codex_input.base_instructions,
    developer_instructions=codex_input.developer_instructions,
    sandbox=Sandbox.read_only,
    config={
        "approval_policy": "never",
        "mcp_servers": {},
        "hooks": {},
    },
)
result = thread.run(
    codex_input.turn_text,
    output_schema=request.output_schema,
    sandbox=Sandbox.read_only,
)
```

验证 `result.status` 和 `final_response`，结构化模式解析 JSON。SDK不接受某个 config键时测试必须失败并据0.147.0真实签名修正，不得删除安全约束。

- [ ] **Step 6: 增加单并发有界队列**

使用 `threading.BoundedSemaphore(1)` 控制活跃 turn；另用原子计数限制最多20个等待者。队列满抛出 `QueueFullError`。

- [ ] **Step 7: 运行测试**

Expected: 角色、结构化、空响应、失败状态、单并发和队列满测试全部通过。

### Task 3: DeepSeek回退与错误分类

**Files:**
- Create: `codex_gateway/app/deepseek_provider.py`
- Create: `codex_gateway/app/router.py`
- Create: `codex_gateway/app/redaction.py`
- Create: `codex_gateway/tests/test_router.py`
- Create: `codex_gateway/tests/test_redaction.py`

**Interfaces:**
- Produces: `CompletionRouter.complete(request) -> RoutedResult`。
- Produces: `should_fallback(exc: Exception) -> bool`。
- Produces: `redact_log_value(value: object) -> object`。

- [ ] **Step 1: 写回退矩阵失败测试**

401、403、429、ServerBusy、认证缺失、超时、空响应和无效 JSON必须回退；非法参数、安全拒绝、取消和队列满不得回退。

- [ ] **Step 2: 写日志脱敏失败测试**

包含 `Authorization`、`access_token`、`refresh_token`、`LLM_API_KEY` 和完整消息正文的输入，输出只能保留错误类别、请求 ID、耗时和消息长度。

- [ ] **Step 3: 实现 DeepSeek Provider**

使用独立配置和 OpenAI SDK，完整转发当前支持的 Chat Completions字段。Fallback Provider不得读取 MiroFish容器全局 `LLM_*`，只读取 `FALLBACK_LLM_*`。

- [ ] **Step 4: 实现 Router**

先调用 Codex；错误符合矩阵时记录结构化 fallback事件，再调用 DeepSeek。`RoutedResult`包含 `provider="codex"|"deepseek"` 和响应内容，但对外响应模型字段保留实际 Provider模型。

- [ ] **Step 5: 运行测试**

Run: `cd codex_gateway && uv run pytest tests/test_router.py tests/test_redaction.py -v`

Expected: 全部通过且测试输出不包含 fake secret原文。

### Task 4: OpenAI-compatible HTTP API 与登录 CLI

**Files:**
- Create: `codex_gateway/app/config.py`
- Create: `codex_gateway/app/api.py`
- Create: `codex_gateway/app/login.py`
- Modify: `codex_gateway/app/__init__.py`
- Create: `codex_gateway/tests/test_api.py`
- Create: `codex_gateway/tests/test_login.py`

**Interfaces:**
- Produces: `POST /v1/chat/completions`。
- Produces: `GET /health`、`GET /account`。
- Produces: CLI `python -m app.login login|status|logout`。

- [ ] **Step 1: 写 API契约失败测试**

覆盖 Bearer内部 Token认证、文本响应、JSON响应、`stream=true`明确400、非法消息400、队列满503和 fallback响应头 `X-MiroFish-Provider`。

- [ ] **Step 2: 写登录 CLI失败测试**

fake SDK返回 verification URL、user code和 Pro account；断言 CLI只显示 URL、code、脱敏 email、planType，不显示 Token。

- [ ] **Step 3: 实现应用配置验证**

启动必须校验内部 Token、Codex模型、DeepSeek fallback三项、超时、并发和队列范围；日志不得打印环境变量值。

- [ ] **Step 4: 实现 HTTP API**

返回 OpenAI SDK可解析的 `chat.completion` JSON。`/account`只在内部 Token认证后返回 `authenticated`、脱敏 email和 planType。

- [ ] **Step 5: 实现 Device Code CLI**

```python
with Codex(config=build_codex_config()) as codex:
    handle = codex.login_chatgpt_device_code()
    print(handle.verification_url)
    print(handle.user_code)
    completed = handle.wait()
    account = codex.account(refresh_token=True)
```

失败时只显示安全错误类别。logout调用官方 `codex.logout()`。

- [ ] **Step 6: 全量 Gateway测试**

Run: `cd codex_gateway && uv run pytest -v`

Expected: 全部通过，无 warning、Token或完整 prompt输出。

### Task 5: Compose接入与隔离技术验证

**Files:**
- Modify: `docker-compose.production.yml`
- Modify: `.env.production.example`
- Create: `docs/deployment/codex-subscription.md`

**Interfaces:**
- Produces: Compose服务 `codex-gateway` 和命名卷 `codex_auth`。
- Consumes: 现有 DeepSeek Key迁移为 `FALLBACK_LLM_API_KEY`。

- [ ] **Step 1: 增加 Compose服务但不切换 backend**

Gateway配置：仅 `expose: 8080`、auth volume挂载 `/var/lib/codex`、512 MiB限制、健康检查、单 worker、`restart: unless-stopped`。backend仍保持当前 DeepSeek直连。

- [ ] **Step 2: 验证 Compose边界**

Run: `docker compose -f docker-compose.production.yml config --quiet`

检查宿主机端口映射仍只有 Web 3003；Gateway无 `ports`。

- [ ] **Step 3: 服务器构建并启动 Gateway**

同步代码时排除服务器 `.env`。执行 `docker compose build codex-gateway && docker compose up -d codex-gateway`。检查RSS、重启次数和日志脱敏。

- [ ] **Step 4: 用户完成 Device Code登录**

Run: `docker compose exec codex-gateway .venv/bin/python -m app.login login`

用户在官方页面输入 code。随后执行 status，只报告 ChatGPT账户脱敏 email和 planType。

- [ ] **Step 5: 容器重启持久化验证**

重启 Gateway，再运行 status和真实普通文本请求；确认无需重新登录。

- [ ] **Step 6: 真实结构化输出验证**

向内部 `/v1/chat/completions` 发送最小 JSON Schema请求，验证返回合法 JSON且 Provider为Codex。

- [ ] **Step 7: 真实回退验证**

使用仅测试进程的 fake Codex错误注入模拟429，不注销真实账号、不破坏 auth volume；验证同请求由 DeepSeek成功返回并记录 fallback原因。

- [ ] **Step 8: 技术验证门禁**

仅当登录持久化、文本、JSON Schema、回退、RSS和日志全部通过，才允许进入 Task 6。任一失败则停止 Gateway并保持生产DeepSeek直连。

### Task 6: 全部 MiroFish LLM流量切换与端到端验证

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env.production.example`
- Modify: `docker-compose.production.yml`
- Test: `backend/tests/test_llm_gateway_configuration.py`

**Interfaces:**
- Consumes: `http://codex-gateway:8080/v1` 和内部 Bearer Token。
- Produces: 所有文本 LLM调用经 Gateway；Embedding继续使用 `GRAPHITI_EMBEDDING_BASE_URL`。

- [ ] **Step 1: 写配置边界失败测试**

断言文本 `LLM_BASE_URL` 指向 Gateway时，Graphiti LLM同步指向 Gateway，而独立 Embedding仍指向 TEI；DeepSeek Key不再出现在 backend容器环境中。

- [ ] **Step 2: 更新生产配置**

backend使用内部 Gateway Base URL和 Token；Gateway独占 fallback DeepSeek配置。Compose增加 backend对 Gateway health依赖，但 Gateway失败不阻止 backend启动，以便明确错误和回滚。

- [ ] **Step 3: 运行本地测试和镜像构建**

Run: `python3 -m pytest backend/tests codex_gateway/tests -v`

Run: `docker compose -f docker-compose.production.yml build backend codex-gateway`

- [ ] **Step 4: 部署并验证基础调用**

重建 Gateway和 backend，验证首页、backend health、Gateway account和普通Chat Completion。

- [ ] **Step 5: 逐链路验收**

按顺序执行最小输入：本体生成、Graphiti建图、人物生成、最小模拟、报告生成、互动问答。每步检查实际 Provider；若回退则记录原因并判断是否属于预期限额。

- [ ] **Step 6: 资源与既有服务验收**

检查四个原容器、Gateway、FRPS和Epic Games状态；OpenClaw/MySQL保持inactive。确认Gateway RSS不超512 MiB、无重启风暴、宿主机available内存和Swap可接受。

- [ ] **Step 7: 回滚演练**

将 backend临时恢复DeepSeek直连并重建，验证基础请求成功；再恢复Gateway配置。演练不得删除 `codex_auth`、Neo4j或上传数据卷。

- [ ] **Step 8: 最终敏感信息与Git检查**

Run: `rg -n 'sk-[A-Za-z0-9_-]{20,}|refresh_token|access_token' --hidden -g '!.git/**' -g '!*.lock' .`

只允许测试假值和文档字段名，不允许真实 Token/Key。运行 `git diff --check`、全量测试并列出待提交文件；未经用户授权不提交。
