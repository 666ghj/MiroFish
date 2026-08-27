# Direct OAuth Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增参考OpenCode CodexAuthPlugin的实验性ChatGPT Direct OAuth Provider，让Graphiti通过Codex Responses后端完成高吞吐结构化抽取，而其他MiroFish任务继续使用官方Codex app-server Gateway。

**Architecture:** 独立`direct_gateway`容器管理Device Code OAuth、0600凭据文件、Token刷新和Codex Responses SSE。它对Graphiti暴露OpenAI-compatible非流式Chat Completions接口；backend通过独立`GRAPHITI_LLM_*`配置指向该服务。Direct Gateway不创建Codex Agent thread/turn，失败时使用DeepSeek fallback和熔断。

**Tech Stack:** Python 3.11、Flask、Gunicorn、httpx、OpenAI-compatible JSON、Docker Compose、pytest

**Spec:** `docs/superpowers/specs/2026-08-27-direct-oauth-provider-design.md`

## Global Constraints

- Provider标记为实验性；OpenCode/OpenAI内部协议变化时必须可一键关闭。
- 不读取或挂载官方Codex Gateway的auth volume。
- OAuth Token不得进入MiroFish backend、日志、Git或HTTP响应。
- Direct Gateway不映射宿主机端口。
- Graphiti批次保持1，Direct最大并发2。
- 派生语料验收前不得启动建图；当前派生语料已完成验收。
- 未经用户明确授权不得提交或推送Git。

---

### Task 1: OAuth协议、JWT元数据与凭据存储

**Files:**
- Create: `direct_gateway/pyproject.toml`
- Create: `direct_gateway/uv.lock`
- Create: `direct_gateway/app/__init__.py`
- Create: `direct_gateway/app/config.py`
- Create: `direct_gateway/app/oauth.py`
- Create: `direct_gateway/app/token_store.py`
- Create: `direct_gateway/tests/test_oauth.py`
- Create: `direct_gateway/tests/test_token_store.py`

**Interfaces:**
- Produces: `DeviceCodeClient.start() -> DeviceAuthorization`
- Produces: `DeviceCodeClient.poll(auth) -> OAuthTokens`
- Produces: `DeviceCodeClient.refresh(refresh_token) -> OAuthTokens`
- Produces: `TokenStore.load/save/clear()`
- Produces: `extract_account_metadata(id_token, access_token) -> AccountMetadata`

- [ ] **Step 1: 写Device Code状态机失败测试**

fake transport覆盖：

- usercode成功。
- 403/404表示pending并按`interval + 3秒`继续。
- 非pending状态失败。
- token exchange body包含authorization code、code verifier、redirect URI和client ID。
- 总登录超时后停止。

- [ ] **Step 2: 写Token刷新失败测试**

过期前60秒刷新；并发请求只触发一次refresh。刷新响应未返回新refresh token时保留旧refresh token。

- [ ] **Step 3: 写JWT安全解析测试**

只解码claims用于account ID、email、plan和residency元数据，不把未验证claims当权限判断。支持顶层和`https://api.openai.com/auth`嵌套account ID。

- [ ] **Step 4: 写凭据存储失败测试**

断言：

- 保存文件权限0600。
- 临时文件原子替换。
- JSON不包含authorization code、device_auth_id或code verifier。
- `status`只返回脱敏email、plan和过期时间。
- clear删除凭据文件。

- [ ] **Step 5: 实现配置**

默认值与OpenCode当前源码一致：

```text
client_id=app_EMoamEEZ73f0CkXaXp7hrann
issuer=https://auth.openai.com
device_start=/api/accounts/deviceauth/usercode
device_poll=/api/accounts/deviceauth/token
token_endpoint=/oauth/token
redirect_uri=https://auth.openai.com/deviceauth/callback
codex_endpoint=https://chatgpt.com/backend-api/codex/responses
```

所有值允许环境变量覆盖。启动校验endpoint必须为HTTPS，测试环境显式允许localhost HTTP。

- [ ] **Step 6: 实现OAuth和TokenStore**

使用`httpx.Client`和注入transport；轮询只记录安全状态码。TokenStore路径固定为`/var/lib/direct-oauth/credentials.json`，写入前创建0700目录。

- [ ] **Step 7: 运行测试并锁依赖**

Run: `cd direct_gateway && uv lock && uv run --extra dev pytest tests/test_oauth.py tests/test_token_store.py -v`

### Task 2: Responses请求转换与SSE解析

**Files:**
- Create: `direct_gateway/app/messages.py`
- Create: `direct_gateway/app/schema.py`
- Create: `direct_gateway/app/responses_client.py`
- Create: `direct_gateway/tests/test_messages.py`
- Create: `direct_gateway/tests/test_schema.py`
- Create: `direct_gateway/tests/test_sse.py`

**Interfaces:**
- Produces: `build_responses_payload(chat_request) -> dict`
- Produces: `normalize_output_schema(schema) -> dict`
- Produces: `parse_responses_sse(lines) -> DirectProviderResult`
- Produces: `ResponsesClient.complete(chat_request) -> DirectProviderResult`

- [ ] **Step 1: 写消息转换失败测试**

system/developer合并为`instructions`；user/assistant/tool按顺序转换为input items；不得把内部Gateway Token或OAuth Token放进body。

- [ ] **Step 2: 写结构化输出失败测试**

- text不设置格式。
- json_object映射到Responses JSON Object格式。
- json_schema递归增加`additionalProperties:false`、所有properties加入required、移除default。
- 原始schema不变。

- [ ] **Step 3: 写SSE失败测试**

覆盖：

- 多个`response.output_text.delta`聚合。
- `response.completed`提取usage和model。
- `response.failed`转换安全错误代码。
- 注释、空行、未知事件忽略。
- 异常断流、无completed和空文本失败。
- reasoning delta不进入最终content。

- [ ] **Step 4: 实现请求body**

固定：

```json
{
  "model": "gpt-5.6-luna",
  "instructions": "...",
  "input": [],
  "store": false,
  "stream": true
}
```

只发送当前端点验证支持的字段；不转发Chat Completions的temperature/max_tokens，除非真实旁路测试证明支持。

- [ ] **Step 5: 实现请求头**

- Bearer access token。
- `ChatGPT-Account-Id`。
- `Accept: text/event-stream`。
- `Content-Type: application/json`。
- `originator: mirofish-direct-oauth`。
- 固定版本User-Agent。
- residency存在时加入`x-openai-internal-codex-residency`。

- [ ] **Step 6: 实现SSE客户端**

使用`httpx.Client.stream`，总超时和read timeout可配置。401时只刷新一次并重试；403/429不无限重试。

- [ ] **Step 7: 运行测试**

Run: `cd direct_gateway && uv run --extra dev pytest tests/test_messages.py tests/test_schema.py tests/test_sse.py -v`

### Task 3: OpenAI-compatible API、登录CLI和回退

**Files:**
- Create: `direct_gateway/app/provider.py`
- Create: `direct_gateway/app/fallback.py`
- Create: `direct_gateway/app/api.py`
- Create: `direct_gateway/app/login.py`
- Create: `direct_gateway/app/redaction.py`
- Create: `direct_gateway/Dockerfile`
- Create: `direct_gateway/tests/test_api.py`
- Create: `direct_gateway/tests/test_login.py`
- Create: `direct_gateway/tests/test_fallback.py`

**Interfaces:**
- Produces: `POST /v1/chat/completions`
- Produces: `GET /health`、`GET /account`
- Produces: `python -m app.login login|status|logout`

- [ ] **Step 1: 写API契约失败测试**

内部Bearer认证、text/json响应、明确拒绝`stream=true`、非法请求400、熔断503、Provider响应头。

- [ ] **Step 2: 写登录CLI失败测试**

只输出官方URL、user code、脱敏账户和plan。Token、device_auth_id、authorization code不得输出。

- [ ] **Step 3: 写回退与熔断失败测试**

- Direct 401先refresh一次。
- refresh失败打开auth熔断。
- 403/429打开临时熔断。
- 连续3次SSE/Schema失败打开protocol熔断。
- DeepSeek 402第一次后永久熔断至进程重启。

- [ ] **Step 4: 实现API和Provider Router**

Direct优先，DeepSeek fallback。不得回退到官方Codex app-server。结构化日志只记录request ID、provider、耗时、状态和安全错误代码。

- [ ] **Step 5: 实现Dockerfile**

Python 3.11、单worker、最大并发2、HTTP线程数至少64、凭据目录0700、内存上限由Compose设置。

- [ ] **Step 6: 全量测试与敏感信息扫描**

Run: `cd direct_gateway && uv run --extra dev pytest -v`

扫描不允许真实Token、Key、服务器IP或credentials内容。

### Task 4: Graphiti独立LLM配置

**Files:**
- Modify: `backend/app/services/zep_graphiti_impl.py`
- Modify: `backend/tests/services/test_zep_graphiti_impl.py`
- Modify: `.env.production.example`

**Interfaces:**
- Consumes: `GRAPHITI_LLM_API_KEY`、`GRAPHITI_LLM_BASE_URL`、`GRAPHITI_LLM_MODEL`
- Preserves fallback: `OPENAI_*`和`LLM_*`

- [ ] **Step 1: 写独立配置失败测试**

当Direct配置存在时，Graphiti LLM使用Direct URL/Token/model；Embedding仍使用`GRAPHITI_EMBEDDING_*`；普通`LLM_BASE_URL`仍指向官方Gateway。

- [ ] **Step 2: 实现配置优先级**

```python
api_key = GRAPHITI_LLM_API_KEY or OPENAI_API_KEY
base_url = GRAPHITI_LLM_BASE_URL or OPENAI_BASE_URL
model = GRAPHITI_LLM_MODEL or LLM_MODEL_NAME
```

DeepSeek特殊客户端只根据最终Graphiti base URL判断。

- [ ] **Step 3: 运行后端测试**

Run: `python3 -m pytest backend/tests -v`

### Task 5: Compose旁路部署与真实OAuth验证

**Files:**
- Modify: `docker-compose.production.yml`
- Modify: `.env.production.example`
- Create: `docs/deployment/direct-oauth-provider.md`

**Interfaces:**
- Produces: `direct-oauth-gateway:8090`和`direct_oauth_credentials` volume。

- [ ] **Step 1: 增加旁路服务**

仅`expose:8090`，不修改backend Graphiti URL。内存384 MiB，healthcheck，auth volume，restart unless-stopped。

- [ ] **Step 2: 服务器构建和测试**

先构建测试镜像并运行全量测试，失败不启动服务。

- [ ] **Step 3: Device Code登录**

用户完成单独OAuth授权。重启容器后status仍有效。

- [ ] **Step 4: 真实text/json_schema验证**

只输出HTTP状态、Provider、模型、内容非空和Schema合法，不输出内容与Token。

- [ ] **Step 5: 一块派生语料Graphiti验证**

从`extracted_text_recent_3y.txt`取第一块，创建临时graph ID，完成节点/边读取后删除。记录耗时并与官方Gateway对比。

### Task 6: 切换Graphiti并启动派生语料建图

**Files:**
- Server environment only after verification.

- [ ] **Step 1: 技术门禁**

OAuth持久化、text、复杂Schema、单块建图和容器资源全部通过才允许切换。

- [ ] **Step 2: 设置Graphiti独立Provider**

backend环境指向`direct-oauth-gateway:8090/v1`，普通LLM仍指向`codex-gateway:8080/v1`。重建backend并验证安全配置。

- [ ] **Step 3: 使用派生语料启动建图**

请求：

```json
{
  "project_id": "proj_ebb7ae725574",
  "corpus": "recent_3y",
  "chunk_size": 8000,
  "chunk_overlap": 200,
  "force": true
}
```

- [ ] **Step 4: 首批门禁**

必须推进到第2批并写入节点/边，且无OAuth、SSE、队列或Schema错误，才交付后台运行。

- [ ] **Step 5: 最终验证**

检查所有容器、端口、内存、Swap、OAuth日志脱敏、项目状态和原文/派生文本哈希。未经用户授权不提交。
