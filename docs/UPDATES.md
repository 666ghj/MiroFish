# 功能更新与使用说明（v0.2.0-beta 开发预览版）

> ⚠️ **注意**: 这是开发预览版本，功能可能不稳定，仅供测试和反馈使用。

## 你会看到的主要变化

- **History 页面**：新增 `/history`，按 **Project → Simulation → Report** 的嵌套关系浏览历史，并可一键跳转到 Step2/Step3/Report/Chat。
- **断点续跑（报告）**：
  - `Continue` 会在同一个 `report_id` 上从未完成章节继续生成（不重复生成已完成章节）。
  - `Regenerate` 会为同一个 `simulation_id` 创建新的 `report_id`（旧报告保留在历史中）。
- **Interview 环境保活（关键）**：报告里的 `interview_agents` 需要模拟进入 **waiting/alive** 模式；后端支持"只重连，不原地重启"，避免破坏历史数据。
- **安全激活（不污染分支）**：当旧模拟环境不可恢复时，前端提供 `Activate (safe)`：自动创建新的 **simulation branch**（新 `simulation_id`），在新分支上运行 Step3 来恢复 Interview 环境，原分支目录不被修改。
- **代码版本检测与自动重启**：后端自动检测 `run_parallel_simulation.py` 脚本的代码版本（MD5），当检测到代码更新时，会自动终止旧进程并提示重启，确保使用最新代码。
- **ReportAgent 工具调用稳定**：章节生成改为 OpenAI 原生 `tool_calls`（不依赖模型输出 `<tool_call>` 文本），减少"未注册工具"类干扰。
- **LLM 模型设置**：新增 Settings 页面（`/settings`），支持查看可用模型列表、切换默认模型。
- **一键烟测**：新增 `scripts/smoke.mjs`（quick/full），用于本地端到端验证。

## 如何正确“继续生成/重新生成”（避免污染）

### 1) 先确认 Interview 环境是否 Alive

- Step4（Report）右侧有 `Interview Env` 状态卡：
  - `env_alive=true`：可以安全继续/重新生成报告（会调用原模拟环境，不会重启模拟目录）。
  - `env_alive=false`：无法采访；需要 **先恢复环境**（见下一节）。

### 2) 当 `env_alive=false` 时如何恢复

- 推荐使用 Step4 的 `Activate (safe)`：
  - 创建新 `simulation_id`（分支）
  - 自动跳转 Step3 运行模拟，直到进入 `alive`
  - 再回到 Step4 继续生成/重新生成

> 注意：如果多个报告任务共用同一个 `simulation_id`，它们共享同一个 Interview 环境；不要在其中一个任务中手动 `close-env`，否则会影响其它仍在生成的任务。

## 本地配置（MiroFish-config + Clash Verge）

### 配置加载优先级

后端会按以下优先级读取环境变量：
1. `MIROFISH_ENV_FILE`（显式指定）
2. 仓库根目录 `.env`
3. `MiroFish-config/.env`

### HTTP(S) Proxy（可选）

在 `.env` 或 `MiroFish-config/.env` 中设置：

```env
HTTP_PROXY=http://127.0.0.1:<proxy-port>
HTTPS_PROXY=http://127.0.0.1:<proxy-port>
NO_PROXY=127.0.0.1,localhost
```

### LLM Base URL

- 后端 `LLM_BASE_URL` 支持配置为你自己的 OpenAI-compatible endpoint（例如 `https://your-endpoint` 或 `https://your-endpoint/v1`；系统会归一化为包含 `/v1` 的形式）。
- OASIS 模拟子进程同样会使用 `LLM_BASE_URL`（并设置 `OPENAI_BASE_URL` 等兼容变量）。

## 运行与验证

- 启动：`npm run dev`
- 后端单测：`cd backend && .venv/bin/python -m pytest -q`
- 前端构建：`npm run build`
- 烟测：
  - Quick（非破坏性）：`npm run smoke`
  - Full（会创建新 project/simulation/report，可能消耗 token）：`npm run smoke:full`
  - Full + 自动清理：`npm run smoke:full:cleanup`

## 排障（最常见）

- 报告“卡住”：通常是等待 `interview_agents` 返回（可能需要几分钟）。
  - 查看：`backend/uploads/reports/<report_id>/console_log.txt`
  - 结构化工具调用审计：`backend/uploads/reports/<report_id>/agent_log.jsonl`
- Interview 失败/超时：
  - 先看 Step4 的 `Interview Env` 是否 `alive`
  - 必要时用 `Activate (safe)` 创建分支恢复环境
