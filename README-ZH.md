# My Own Researcher

My Own Researcher is an independent fork of [MiroFish](https://github.com/666ghj/MiroFish), distributed under [AGPL-3.0](LICENSE).

本项目是 MiroFish 的独立分支。此分支的安装、功能和限制以 **[英文 README](README.md)** 为准；[上游中文文档](https://github.com/666ghj/MiroFish/blob/main/README-ZH.md) 介绍原始 MiroFish，不能直接替代此分支的本地安装步骤。

此分支默认使用英文界面、用户自己的 Codex 登录，以及本地 Graphiti/Neo4j 图谱存储。本地模式无需 Zep 账号或 LLM API 密钥，但 AI 推理仍会将文档和模拟内容发送给 OpenAI，并消耗账号可用额度；并非离线或无限免费推理。

支持通过 MCP 供其他 AI Agent 复用研究流程。网页默认地址为 `http://localhost:4317`，MCP Streamable HTTP 地址为 `http://127.0.0.1:4318/mcp`。安装后可运行 `npm run graph:up` 和 `npm run dev:agent`，无需打开网页；stdio 配置、工具调用顺序和恢复方法见 [MCP 使用指南](docs/mcp.md)。

For this fork's setup, recovery controls, and data handling, see the [canonical English README](README.md), [workbench guide](docs/my-own-researcher.md), and [Codex provider guide](docs/codex-provider.md). Original MiroFish attribution and the license are retained.
