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
