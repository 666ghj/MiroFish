# MiroFish Neo4j 二开版

[English](./README.md) | 中文

<a href="https://trendshift.io/repositories/16144" target="_blank"><img src="https://trendshift.io/api/badge/repositories/16144" alt="MiroFish | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

本项目基于原始开源仓库 [666ghj/MiroFish](https://github.com/666ghj/MiroFish) 进行二次开发。

本版本的核心改动是：将原项目中的 Zep Cloud 图谱记忆与检索依赖替换为本地 Neo4j 后端，使项目可以使用本地图数据库完成实体关系存储、图谱检索、报告工具调用和模拟后的记忆更新，同时保留原 MiroFish 的多智能体模拟流程。

本项目遵守原仓库一致的开源协议：**AGPL-3.0**。

## 主要改动

- 使用本地 Neo4j 替代 Zep Cloud 图谱存储与检索。
- 新增 Neo4j 图谱构建、实体读取、记忆更新和搜索服务。
- 新增图数据库后端工厂，支持按配置切换图谱后端。
- 修复并增强报告工具输出：
  - Deep Insight
  - Panorama Search
  - Quick Search
- 新增 LLM 429 限流等待与重试逻辑。
- 新增足球场景的比分概率计算与报告注入。
- 新增本地 Neo4j Docker Compose 配置。

## 功能说明

- 上传种子文档并抽取实体关系。
- 将抽取结果写入本地 Neo4j 图谱。
- 生成模拟 Agent 和社交行为配置。
- 运行双平台社交模拟。
- 基于图谱检索生成预测报告。
- 在足球比赛场景中输出胜平负概率、最可能比分、期望进球和比分矩阵。

## 项目结构

```text
frontend/                 Vue + Vite 前端
backend/                  Flask 后端
backend/app/services/     模拟、报告、图谱与适配服务
backend/app/services/adapters/
                           Neo4j 图谱适配实现
backend/app/utils/neo4j/  Neo4j 驱动与 Schema 工具
locales/                  多语言文案
static/                   静态图片资源
```

## 环境要求

- Node.js 18+
- Python 3.11 - 3.12
- uv
- Docker（用于快速启动 Neo4j）
- 一个兼容 OpenAI SDK 格式的 LLM API Key

## 环境变量配置

复制示例文件：

```bash
cp .env.example .env
```

最小本地配置示例：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j
```

可选的 LLM 限流重试配置：

```env
LLM_RATE_LIMIT_MAX_ATTEMPTS=20
LLM_RATE_LIMIT_INITIAL_DELAY=30
LLM_RATE_LIMIT_MAX_DELAY=180
LLM_RATE_LIMIT_BACKOFF_FACTOR=1.5
```

## 启动 Neo4j

项目提供了本地 Neo4j 的 Docker Compose 文件：

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

默认地址：

- Neo4j Browser：`http://localhost:7474`
- Bolt URI：`bolt://localhost:7687`
- 默认账号：`neo4j / password`

请确保 `.env` 中的 `NEO4J_PASSWORD` 与 Docker Compose 中配置的密码一致。

## 安装依赖

一次性安装前后端依赖：

```bash
npm run setup:all
```

也可以分开安装：

```bash
npm run setup
npm run setup:backend
```

## 运行项目

同时启动前端和后端：

```bash
npm run dev
```

服务地址：

- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:5001`

单独启动：

```bash
npm run backend
npm run frontend
```

## Docker 运行

根目录的 `docker-compose.yml` 可用于启动应用容器。若使用本地 Neo4j 图谱后端，建议先启动 Neo4j：

```bash
docker compose -f docker-compose.neo4j.yml up -d
```

再启动应用：

```bash
docker compose up -d
```

默认会读取根目录下的 `.env`，并映射端口 `3000（前端）/5001（后端）`。

## 基本使用流程

1. 启动 Neo4j。
2. 启动后端和前端。
3. 打开 `http://localhost:3000`。
4. 创建或打开项目。
5. 上传种子文档。
6. 构建图谱。
7. 生成模拟配置。
8. 启动模拟。
9. 生成预测报告。

## 报告检索工具

报告 Agent 可以调用以下图谱检索工具：

- **Deep Insight**：将问题拆解为多个子问题，并收集相关事实、实体和关系链。
- **Panorama Search**：返回图谱中的全景实体和事实。
- **Quick Search**：对图谱事实、节点名称和节点摘要进行轻量关键词搜索。
- **Interview Agents**：结合模拟或图谱上下文生成面向 Agent 的回答。

在 Neo4j 二开版中，检索工具会输出前端可直接解析的文本结构，因此报告时间线能够展示事实、实体和关系链，而不是空白 JSON。

## 足球比分概率报告

当模拟需求或种子数据包含足球、比分、泊松、lambda、xG、expected goals 等信号时，后端会尝试抽取：

- `lambda_home`
- `lambda_away`
- xG / expected goals
- 主客队信息

并生成：

- 主胜 / 平局 / 客胜概率
- 最可能比分 Top Scorelines
- 期望进球
- 比分概率矩阵

该部分会作为确定性计算结果注入报告，避免报告只停留在 LLM 的泛化描述。

## 日志位置

常用本地日志：

```text
log/backend-restart.out.log
log/backend-restart.err.log
log/frontend-direct.out.log
log/frontend-direct.err.log
backend/uploads/reports/<report_id>/agent_log.jsonl
backend/uploads/reports/<report_id>/console_log.txt
```

## 常见问题

### Neo4j 连接失败

确认 Neo4j 已启动，并检查 `.env` 中的 Neo4j 配置是否与 Docker Compose 一致。

```bash
docker compose -f docker-compose.neo4j.yml ps
```

### LLM 返回 429

后端已内置限流重试逻辑。遇到 429 时会根据 `LLM_RATE_LIMIT_*` 配置等待后继续重试。

### Deep Insight / Panorama Search / Quick Search 内容为空

请确认项目已经成功构建图谱。Neo4j 检索会搜索关系事实、节点名称和节点摘要；如果图谱本身没有内容，工具也无法返回有效结果。

### 报告缺少比分预测

请确认模拟需求或种子数据包含足球相关关键词，并提供可抽取的 `lambda_home`、`lambda_away`、xG 或 expected goals 信息。

## 开源协议

本项目继承原仓库协议，使用 **AGPL-3.0**。

如果你部署、分发，或通过网络提供该软件服务，请遵守 AGPL-3.0 的相关要求。

## 致谢

本项目基于 [666ghj/MiroFish](https://github.com/666ghj/MiroFish) 进行二次开发。感谢原作者及所有贡献者的开源工作。