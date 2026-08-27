# ChatGPT 订阅 Codex Provider 设计

## 目标

为单用户 MiroFish-local 增加基于官方 Codex app-server 的 ChatGPT Plus/Pro 订阅 Provider：所有文本 LLM 任务默认使用 ChatGPT 订阅额度，DeepSeek 在认证失效、订阅限流、超时或结构化输出失败时自动回退。本地 Embedding 与 Neo4j 保持不变。

本设计不把 ChatGPT 订阅伪装成 OpenAI Platform API Key。Codex OAuth、Token 持久化和刷新全部由官方 Codex runtime 管理。

## 范围

覆盖当前全部文本 LLM 调用：

- 本体生成和图谱信息抽取。
- 人物档案与模拟配置生成。
- OASIS/Twitter/Reddit 模拟脚本使用的模型请求。
- ReportAgent、工具调用和报告生成。
- 报告互动与人物访谈。

不覆盖：

- Embedding；继续由本地 TEI 提供。
- 多用户账户、邀请码和项目数据隔离。
- ChatGPT OAuth 登录页面；首次登录通过服务器终端完成。
- 移除 DeepSeek；DeepSeek 继续作为回退服务。

## 方案选择

### 采用：官方 Codex Python SDK + app-server runtime

使用官方稳定发布的 `openai-codex` Python SDK。SDK 自动安装并固定匹配版本的 Codex CLI runtime，通过 stdio 启动 `codex app-server`。Gateway 使用 SDK 的公开接口完成账户检查、Device Code 登录、模型列表、thread 创建和 turn 执行。

优点：

- OAuth、Token 刷新、ChatGPT account ID 和 planType 由官方 runtime 管理。
- SDK 与 CLI runtime 版本绑定，减少 JSON-RPC 协议漂移。
- 支持 `output_schema` 结构化输出。
- 不复制 OpenCode 的 OAuth client、内部端点和请求头逻辑。

代价：

- 多一个常驻 Gateway 容器和 Codex runtime。
- Codex 是 Agent runtime，调用延迟可能高于普通 Chat Completions。
- ChatGPT 订阅有配额与公平使用限制，不能视为无限 API。

### 不采用：复制 OpenCode CodexAuthPlugin

OpenCode 自己实现 PKCE/device-code、Token 刷新、`ChatGPT-Account-Id` 和 Codex Responses 请求改写。该路径更短，但需要持续追踪内部协议变化，且已有 Token exchange 403、刷新存储和工具协议兼容问题。

### 不采用：直接调用非公开 Codex 后端

直接保存 access/refresh token 并发送内部请求虽然性能更高，但认证安全、协议变化和维护成本不可接受。

## 总体架构

```text
MiroFish Backend / Graphiti / Simulation Scripts
                  |
                  | OpenAI-compatible Chat Completions
                  v
          codex-gateway:8080（Docker 内网）
                  |
       +----------+-----------+
       |                      |
       v                      v
官方 openai-codex SDK     DeepSeek fallback
       |
       v
codex app-server + ChatGPT OAuth
       |
       v
持久化 Docker Volume: CODEX_HOME

Embedding requests -> 本地 TEI（不经过 Gateway）
```

Gateway 对内部消费者暴露 OpenAI-compatible `/v1/chat/completions`，让现有代码只需更换 LLM Base URL，不需要逐一改写各服务和模拟脚本。

Gateway 不映射宿主机端口，仅在 Docker Compose 网络中可访问。

## 组件设计

### 1. Codex Gateway

独立 Python 服务，职责仅包括：

- 管理一个进程内的官方 `AsyncCodex` 客户端。
- 将 Chat Completions 请求转换为 Codex thread/turn。
- 将 Codex `TurnResult` 转换为 Chat Completions 响应。
- 验证 JSON/JSON Schema 输出。
- 控制并发、超时和 DeepSeek 回退。
- 提供内部健康与指标接口。

Gateway 不读取 Codex 的 `auth.json`，只调用 SDK 的 `account()`、`login_chatgpt_device_code()` 和 `logout()`。

### 2. Codex Runtime

由 `openai-codex` SDK 固定并启动匹配的 Codex CLI/app-server runtime。运行配置：

- `CODEX_HOME=/var/lib/codex`，挂载命名卷。
- `approval_policy=never`。
- `sandbox_mode=read-only`。
- 工作目录为空的只读目录，不挂载 MiroFish 源码、上传文件或宿主机目录。
- 禁止 Gateway 请求启用写文件或 full-access sandbox。
- 默认只允许一个活跃 Codex turn，其他请求进入有界队列。

### 3. Device Code 登录工具

首次部署或重新认证时，通过服务器终端执行 Gateway 容器内的登录命令。命令：

1. 启动 SDK Device Code 登录。
2. 输出官方 verification URL 和 user code。
3. 等待用户在浏览器授权。
4. 通过 `account()` 读取 email、planType 和认证状态。
5. 只输出脱敏账户信息，不输出 access/refresh token。

登录工具不通过公网 HTTP 暴露。

### 4. DeepSeek Fallback

Gateway 持有独立的 DeepSeek配置：

- `FALLBACK_LLM_API_KEY`
- `FALLBACK_LLM_BASE_URL`
- `FALLBACK_LLM_MODEL`

现有 DeepSeek Key 从 MiroFish backend 容器迁移到 Gateway 容器；其他容器只拥有内部 Gateway Token，降低外部 Key 暴露范围。

## Chat Completions 兼容层

### 输入

第一阶段支持项目当前实际使用的非流式子集：

- `model`
- `messages`：system、developer、user、assistant、tool
- `temperature`
- `max_tokens`
- `response_format`：text、json_object、json_schema
- 工具结果作为对话文本输入

`stream=true` 明确返回不支持错误；实施前必须验证当前 MiroFish 调用均为非流式。若存在流式调用，则在同一实现中增加 SSE 转换，不允许静默降级。

### 消息转换

每次请求创建 ephemeral Codex thread，避免不同业务调用共享上下文。Gateway 将消息序列编码为明确角色的单个 turn 输入，同时将 system/developer 内容放入 `base_instructions` 或 `developer_instructions`。

Codex thread 固定：

- `approval_mode=never` 对应的非交互模式。
- `sandbox=read_only`。
- 无工具执行需求；提示词明确要求只返回最终答案，不操作文件或执行命令。

### 结构化输出

- `json_schema`：直接映射到 SDK `output_schema`。
- `json_object`：向提示词追加“仅返回合法 JSON”，并在 Gateway 解析验证。
- text：读取 `TurnResult.final_response`。

结构化结果解析失败时，Codex 最多进行一次格式修复 turn；仍失败则回退 DeepSeek。

### 输出

返回现有 OpenAI SDK 可解析的最小 Chat Completion：

- `id`
- `object=chat.completion`
- `created`
- `model`
- `choices[0].message.content`
- `choices[0].finish_reason`
- 可获得时返回 token usage；不可获得时使用 `null` 或零值，并在指标中单独记录。

## 路由与回退策略

ChatGPT 订阅为默认 Provider。以下情况触发 DeepSeek：

- Codex 未登录或 Token 无法刷新。
- ChatGPT/Codex 返回 401、403、429 或订阅额度耗尽。
- ServerBusy/overload 且官方重试策略耗尽。
- 单次调用超过 Gateway 超时。
- `final_response` 为空。
- JSON/JSON Schema 两次验证失败。
- app-server 进程异常退出且一次重启未恢复。

以下情况不自动回退：

- 请求参数非法。
- 输入超过 Gateway 明确限制。
- 内容安全拒绝。
- 客户端主动取消。

每次回退记录原因、任务类别、Codex耗时和 DeepSeek耗时，但不记录 Token、完整 prompt 或完整响应正文。

## 并发与资源控制

ColoCrossing VPS 内存有限。Gateway 初始配置：

- 容器内存上限 512 MiB。
- 最大活跃 Codex turn：1。
- 等待队列长度：20。
- 队列满时返回 503，不直接制造更多 Codex进程。
- 一个 Gateway 进程复用一个 `AsyncCodex` runtime。
- 每个业务调用使用 ephemeral thread，完成后不保留对话状态。

部署后根据真实 RSS 调整，但不得以启动多个 Codex runtime 作为扩容方式。

## 配置

新增通用配置：

- `LLM_PROVIDER=codex_subscription`
- `LLM_BASE_URL=http://codex-gateway:8080/v1`
- `LLM_API_KEY=<内部随机 Token>`
- `LLM_MODEL_NAME=<登录后 model/list 验证的 Codex 模型>`
- `CODEX_MODEL=<同上>`
- `CODEX_REASONING_EFFORT=medium`
- `CODEX_REQUEST_TIMEOUT_SECONDS`
- `CODEX_MAX_CONCURRENCY=1`
- `CODEX_QUEUE_SIZE=20`
- DeepSeek fallback 三项配置

Graphiti Embedding继续使用独立的 `GRAPHITI_EMBEDDING_*`，不得指向 Codex Gateway。

## 安全

- Gateway 和 app-server 不暴露公网端口。
- Codex auth volume 仅挂载到 Gateway 容器。
- Gateway 内部 API 使用随机 Token，避免同一 Docker 网络中的其他容器任意调用。
- 不在日志中输出 Authorization、OAuth Token、Device Code 登录返回体或 `.env`。
- Codex sandbox 固定 read-only，approval 固定 never。
- Codex工作目录不挂载用户上传目录，防止模型通过 Agent 工具读取资料之外的服务器文件。
- 服务器备份不得包含未加密导出的 OAuth Token；备份 auth volume 时按敏感凭据处理。

## 数据与隐私

业务 prompt 会通过 ChatGPT/Codex 服务处理。用户上传资料是否适合发送给该服务由部署者负责判断。DeepSeek回退时同一 prompt 可能发送给 DeepSeek。UI/文档应明确说明双 Provider 数据流。

## 可观测性

Gateway 提供仅内部访问的：

- `/health`：进程和 SDK 状态。
- `/account`：仅返回是否登录、脱敏 email、planType。
- `/metrics` 或结构化日志：Codex调用次数、回退次数、原因、延迟、队列长度。

MiroFish系统状态页只需展示：ChatGPT已连接/未连接、套餐、当前首选 Provider、最近回退原因；第一阶段可先通过服务器诊断命令读取，不要求新增前端 UI。

## 实施阶段

### 阶段 1：技术验证

在不修改现有生产路由的情况下验证：

1. Gateway 镜像能安装官方 SDK 和匹配 runtime。
2. Device Code 登录成功并在容器重启后保持登录。
3. 普通文本请求返回结果。
4. `output_schema` 返回合法 JSON。
5. 模拟 Codex 429/未登录时正确回退 DeepSeek。
6. Gateway 进程 RSS 满足 512 MiB 限制。

任一项失败则停止，不将现有 MiroFish Base URL 切换到 Gateway。

### 阶段 2：OpenAI-compatible Gateway

实现请求/响应转换、并发队列、超时、日志脱敏和自动回退，并用 mock Codex SDK/DeepSeek覆盖测试。

### 阶段 3：MiroFish接入

将文本 LLM Base URL 切换到内部 Gateway，确认所有调用点均经过 Gateway；Embedding继续直连 TEI。

### 阶段 4：端到端验证

依次验证本体生成、Graphiti 建图、人物生成、最小模拟、报告生成和互动问答。记录哪些调用走 Codex，哪些触发 DeepSeek回退。

## 测试

- OAuth状态与未登录错误映射。
- 普通 text、json_object、json_schema兼容。
- system/developer/user/assistant消息顺序。
- 空响应和无效 JSON 修复。
- 401/403/429/ServerBusy/超时回退。
- 非回退错误保持原始状态码。
- 并发上限、队列满和取消。
- Token和 prompt 日志脱敏。
- Codex容器重启后账户状态保持。
- MiroFish所有现有 LLM调用的契约测试。
- 真实最小端到端测试和宿主机资源检查。

## 部署与回滚

部署时先新增 Gateway 容器但不切换 MiroFish。完成登录和技术验证后，才更新 MiroFish文本 LLM Base URL并重建后端。

回滚只需：

1. 将 MiroFish LLM配置恢复为现有 DeepSeek直连。
2. 重建后端容器。
3. 停止 Gateway容器但保留 Codex auth volume。

回滚不影响 Neo4j、Embedding或已有项目数据。

## 验收标准

- 官方 Device Code 登录成功，显示 Pro/Plus planType。
- 容器重启后无需重新登录。
- 普通文本与 JSON Schema真实请求成功。
- 至少一次模拟故障成功回退 DeepSeek。
- 本体、建图、模拟、报告和互动全链路完成。
- Gateway不暴露公网，Token不出现在日志和 Git。
- MiroFish现有 DeepSeek直连回滚路径可在一次容器重建内恢复。
- 服务器内存、Swap和容器重启次数处于可接受范围。
