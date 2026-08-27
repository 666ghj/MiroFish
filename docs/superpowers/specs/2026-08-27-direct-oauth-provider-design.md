# Direct OAuth Provider 设计

## 目标

新增实验性Direct OAuth Provider，参考OpenCode的CodexAuthPlugin实现ChatGPT Device Code/PKCE登录、Token刷新和Codex Responses请求改写。Graphiti批量结构化抽取优先使用Direct Provider，绕过官方Codex app-server的Agent thread/turn生命周期。

官方Codex app-server Gateway继续服务于报告、问答和一般分析。DeepSeek保留为最后回退。

## 实验性边界

Direct Provider依赖ChatGPT订阅的非标准Codex后端接口，不是OpenAI Platform公开通用API。OpenAI或OpenCode协议变化可能导致登录、刷新、模型或请求格式失效。

必须满足：

- 可通过环境变量一键禁用。
- Graphiti可切回官方Gateway或DeepSeek。
- 不复用或读取官方Codex app-server的auth.json。
- 独立OAuth凭据卷，独立登录和登出。

## 架构

```text
Graphiti
  -> OpenAI-compatible /v1/chat/completions
  -> direct-oauth-gateway
  -> ChatGPT Codex Responses endpoint

其他MiroFish文本任务
  -> codex-gateway
  -> 官方openai-codex app-server

Embedding
  -> TEI
```

两个Gateway都只在Docker内网暴露，不映射宿主机端口。

## OAuth

支持Device Code登录，流程参考OpenCode：

1. 请求Device Authorization，获得`device_auth_id`、`user_code`和轮询间隔。
2. 用户在官方Codex Device页面输入code。
3. 轮询Device Token接口，获得authorization code和code verifier。
4. 交换access token、refresh token、id token和过期时间。
5. 从JWT claims提取`chatgpt_account_id`和plan type。
6. access token过期前自动使用refresh token刷新。

OAuth client、issuer、scope和endpoint集中配置，禁止散落硬编码。默认scope按当前OpenCode实现及实际端点要求锁定，升级前必须重新验证。

## 凭据存储

独立Docker Volume挂载到`/var/lib/direct-oauth`。凭据文件：

- 权限0600。
- 使用临时文件+原子替换。
- 只包含OAuth必要字段、account ID和expires_at。
- 日志永不输出Token、authorization code、device_auth_id或完整JWT claims。
- MiroFish backend、官方Codex Gateway和Web容器均不能挂载该卷。

第一阶段使用容器文件权限和Docker Volume隔离。可选的应用层加密不在首版范围，因为解密密钥与服务同机时不能替代主机安全。

## 请求协议

对内暴露当前MiroFish使用的非流式Chat Completions子集：

- `messages`
- `model`
- `temperature`
- `max_tokens`
- `response_format`：text、json_object、json_schema

转换到Responses请求：

- system/developer消息合并为instructions。
- user/assistant/tool消息转换为input items。
- `store=false`。
- `stream=true`，因为Codex后端返回SSE。
- JSON Schema映射到Responses结构化输出字段，并执行与现有Gateway一致的严格Schema规范化。

响应解析：

- 逐行解析SSE。
- 聚合assistant文本delta。
- 捕获response.completed、response.failed和usage。
- 转换为普通非流式Chat Completion响应。
- 不把reasoning内容返回给Graphiti或写入日志。

## 请求头与端点

Provider根据当前OpenCode实现设置：

- `Authorization: Bearer <access_token>`
- `ChatGPT-Account-Id: <account_id>`
- `Content-Type: application/json`
- `Accept: text/event-stream`
- 明确的originator/User-Agent

Codex Responses endpoint由配置提供，默认值以实施时验证的OpenCode当前源码为准。禁止将endpoint暴露到前端。

## Provider路由

新增Graphiti独立配置：

- `GRAPHITI_LLM_API_KEY`：内部Gateway Token。
- `GRAPHITI_LLM_BASE_URL=http://direct-oauth-gateway:8090/v1`
- `GRAPHITI_LLM_MODEL=gpt-5.6-luna`
- `GRAPHITI_LLM_PROVIDER=direct_oauth`

`zep_graphiti_impl`优先读取独立Graphiti LLM配置，未设置时回退现有`OPENAI_*`，保持兼容。

其他文本任务继续使用：

- `LLM_BASE_URL=http://codex-gateway:8080/v1`

## 回退与熔断

Graphiti路由顺序：

1. Direct OAuth Provider。
2. 可配置的DeepSeek fallback。

不自动回退到官方Codex app-server，避免批量任务再次进入Agent turn超时。

触发熔断：

- OAuth刷新失败或401/403。
- 429或额度耗尽。
- endpoint协议不兼容。
- 连续3次SSE/结构化解析失败。
- DeepSeek 402保持现有余额不足熔断。

熔断后新请求快速失败，重启或重新登录后恢复。日志只记录安全错误代码。

## 并发

Direct Provider首版最大并发2，队列长度50。Graphiti生产建图批次保持1。HTTP工作线程必须多于队列消费者和健康检查需求。

## Compose与资源

新增`direct-oauth-gateway`：

- 独立Dockerfile和依赖锁。
- 内存上限384 MiB。
- 仅`expose: 8090`。
- 独立healthcheck。
- 独立auth volume。
- 不挂载源码、上传目录或Neo4j数据。

## 登录CLI

服务器终端命令：

```text
python -m app.login login
python -m app.login status
python -m app.login logout
```

只输出官方验证URL、user code、脱敏账户和套餐。

## 测试

- PKCE和Device Code状态机。
- Pending、expired、denied和成功授权。
- JWT account ID提取，不信任未验证claims做权限判断。
- Token原子保存、权限和刷新。
- 请求头不泄漏。
- Chat消息到Responses转换。
- text/json_object/json_schema。
- SSE分片、completed、failed和异常断流。
- 401/403/429、刷新失败、解析失败和熔断。
- DeepSeek 402熔断。
- Direct Provider与官方Gateway配置隔离。
- 容器重启后OAuth持久化。
- 真实小文本、真实复杂Graphiti Schema和一块派生语料建图。

## 分阶段上线

1. 旁路部署，不修改Graphiti Base URL。
2. 完成Direct OAuth登录和真实text/json_schema验证。
3. 用派生语料中的单块做Graphiti建图验证。
4. 将Graphiti切到Direct Provider，其他任务保持官方Gateway。
5. 使用最近3年派生语料启动完整建图。

任一阶段失败立即停止，不继续创建新失败图。

## 回滚

- 将`GRAPHITI_LLM_BASE_URL`恢复为官方Gateway或DeepSeek。
- 重建backend。
- 停止Direct Gateway但保留auth volume。
- 派生语料和原始资料不受影响。

## 验收标准

- Device Code登录成功，容器重启后仍有效。
- 真实Responses text和复杂JSON Schema通过。
- 单块Graphiti建图不创建Agent thread/turn，耗时显著低于官方Gateway。
- Graphiti和其他MiroFish任务可使用不同Provider。
- Direct Gateway不暴露公网，敏感凭据不进入日志和Git。
- 最近3年派生语料完整建图至少推进超过首批，且无官方Codex Agent超时/队列错误。
