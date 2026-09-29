# MiroFish-novel（novel-mac fork）改造说明

本仓库是 [666ghj/MiroFish](https://github.com/666ghj/MiroFish) 的本地 fork，
冻结基线 `117ed37`（`v0.1.2-100-g117ed37`，2026-08-17），分支 `novel-mac`。
许可证 **AGPL-3.0 沿用**；本文件列出相对基线的全部修改，满足修改声明要求。
改造的决策依据与验收清单在 novel-agent 仓库
`docs/mirofish-group-emergence-fork-plan-2026-09-24.md`。

## 相对基线的修改（按提交）

| 提交 | 内容 |
| --- | --- |
| `e54f882` | ④ 本地图记忆首片：`GRAPH_MEMORY_BACKEND=neo4j_local` 时共享客户端接缝返回 Neo4j 实现（`app/utils/local_graph_memory.py`），`Config.validate()` 按后端分支（云侧强度不变），`neo4j>=5.23.0` 依赖 |
| `5b72acd` + `6795b79` | ① `POST /api/novel/seed`：`NovelMirofishSeed` 严格 schema（`extra=forbid`）、确定性实体/边写入（`add_nodes` 稳定 uuid + `add_fact_triple`）、canonical inputHash、确定性 `simulation_requirement`；无 LLM |
| `dbf4ecd` | ② `ReaderPersona` 实体的 OASIS profile 确定性生成（不经 LLM、无随机后缀）；其他实体路径不变 |
| `95f925b` | ③ 报告小说模式：Project 携带 `novel_seed` 元数据；大纲 prompt 附加 craft 约束与确定性 fallback；最终 markdown 市场断言降级 + 「限制与不确定」节；`ZepToolsService` 构造器本地后端免 Zep key |
| **working tree / M0–M2** | ⑤ Plot Counterfactual 闸门与实验性异步生命周期：typed world snapshot/action/delta、分支、canonical hash、bounded replay、sidecar-local durable run/status/snapshot/diff/stop；当前只标记 `m2-experimental`，不代表 novel-agent 产品能力已接入。 |

## M0–M2 Plot Counterfactual 闸门（实验性）

M0 证明独立于 OASIS 和图记忆后端的 typed world-state 核心：`WorldSnapshot`、typed `WorldAction`、前置条件、`WorldStateDelta`、分支、canonical SHA-256 和 bounded replay。M1 为命名动作增加最小语义边界：移动、容纳、资源转移/消耗、关系状态、知识揭示、故事时间、规则和债务状态；动作仍只能通过 typed precondition/effect 进入状态。

M2 增加持久化的异步运行协议：

- `GET /api/novel/counterfactual/capabilities`
- `POST /api/novel/counterfactual/branch`
- `POST /api/novel/counterfactual/replay`
- `POST /api/novel/counterfactual/run`
- `GET /api/novel/counterfactual/run/<runId>`
- `GET /api/novel/counterfactual/run/<runId>/branches/<branchId>`
- `GET /api/novel/counterfactual/run/<runId>/branches/<branchId>/snapshot`
- `GET /api/novel/counterfactual/run/<runId>/branches/<branchId>/diff`
- `POST /api/novel/counterfactual/run/<runId>/stop`

当前状态是实验性 sidecar protocol，不接入 LLM、OASIS、Neo4j 或 novel-agent Canon；`capabilities.stage` 为 `m2-experimental`，`productModes` 仍为空。运行 registry 将 run request、branch delta/final snapshot 以 sidecar-local JSON store 原子写入 `backend/uploads/counterfactual/runs.json`（可用 `NOVEL_COUNTERFACTUAL_STORE_PATH` 覆盖）；sidecar 重启后已完成 run 可读取，重启时仍在执行的 run 会诚实标为 failed/interrupted，不会伪造 active worker。仍不能据此宣称 Plot Counterfactual 已接入产品；后续必须补 novel-agent adapter 和真实 DSH Host/Workbench 验收。

## 本地运行（macOS）

```bash
# 依赖
cd backend && uv sync

# 本地 Neo4j（示例；端口与 .env 对应）
docker run -d --name mirofish-novel-neo4j -p 17474:7474 -p 17687:7687 \
  -e NEO4J_AUTH=neo4j/<local-password> -v mirofish-novel-neo4j-data:/data neo4j:5.26.30-community

# 配置（仓库根 .env，不入库）
GRAPH_MEMORY_BACKEND=neo4j_local
NEO4J_URI=bolt://localhost:17687
NEO4J_USER=neo4j
NEO4J_PASSWORD=<local-password>
FLASK_HOST=127.0.0.1
FLASK_PORT=5001
LLM_API_KEY=<用户的 OpenAI 兼容 key>
LLM_BASE_URL=https://api.deepseek.com/v1   # 或智谱
LLM_MODEL_NAME=deepseek-chat

# 启动
uv run python run.py   # 仅绑定 127.0.0.1；novel-agent adapter 只连 loopback
```

## 边界

- 云端（`GRAPH_MEMORY_BACKEND=zep` 缺省）行为与上游完全一致，含 `ZEP_API_KEY`
  强制与 `ZEP_API_URL` 拒绝。
- 上游的 batch 文本抽取管线（Zep Cloud 服务端抽取）保持原样；本 fork 的
  确定性入口只有 `POST /api/novel/seed`。
- 所有沙盘结果只是模拟产物：非市场代表、不作预测、不作小说事实；进入
  novel-agent Canon 必须走其提案审阅 → 作者接受流程。
