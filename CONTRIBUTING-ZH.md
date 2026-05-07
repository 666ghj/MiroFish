# Contributing to MiroFish

English version: [CONTRIBUTING.md](./CONTRIBUTING.md)

感谢你关注并参与 MiroFish 社区贡献。我们欢迎 Bug 反馈、功能建议、文档改进和代码贡献。开始之前请先阅读项目总览与环境说明：[README.md](./README.md)。本指南的简体中文版本即当前文档，对应英文版本见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## Code of Conduct

请在所有交流中保持尊重、建设性和包容性。我们鼓励在 Issues、Discussions 和 Pull Request 中进行清晰沟通与高质量协作。

## How to Report Bugs

1. 提交前先搜索现有 Issues，避免重复。
2. 在 [GitHub Issues](https://github.com/666ghj/MiroFish/issues) 页面创建新问题。
3. 请提供以下信息：
   - 操作系统及版本
   - Python 版本
   - Node.js 版本
   - 可复现问题的步骤
   - 完整错误 traceback 或日志
   - 当前使用的 LLM provider 和 model（这是本仓库常见问题来源）

## How to Suggest Features

1. 在 GitHub 提交 Issue，并添加 `enhancement` label。
2. 说明你的 use case 和实际问题背景，而不仅是功能名称。
3. 先检查当前打开的 Pull Requests；仓库迭代很快，你的想法可能已在开发中。

## Development Setup

```bash
# 1. Fork and clone
git clone https://github.com/YOUR_USERNAME/MiroFish.git
cd MiroFish

# 2. Copy env file and fill in your API keys
cp .env.example .env
# Required: LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, ZEP_API_KEY

# 3. Install all dependencies (Node + Python via uv)
npm run setup:all

# 4. Start development servers
npm run dev
# Frontend: http://localhost:3000
# Backend:  http://localhost:5001
```

`npm run setup:all` 会安装 frontend 和根目录的 Node.js 依赖，并使用 `uv` 创建并准备 Python 虚拟环境。

## Project Structure

- `backend/` - Python FastAPI backend、simulation engine、LLM client、graph builder
- `frontend/` - Vue.js frontend
- `locales/` - i18n 翻译文件
- `.env.example` - 所有可配置环境变量

## Making a Pull Request

1. 始终从最新的 `main` 分支切出新分支。
2. 分支命名建议使用以下模式之一：
   - `feat/your-feature`
   - `fix/your-fix`
   - `docs/your-docs`
3. 保持 PR 聚焦：一个 PR 只解决一个核心问题。
4. 认真填写 PR 描述，清楚说明：
   - 改了什么（WHAT）
   - 为什么改（WHY）
5. 如有关联 Issue，请在描述中引用，例如：`Closes #123`。
6. 提交前请确认 `npm run dev` 可以无报错启动。

## Commit Message Convention

推荐使用 Conventional Commits：

- `feat:` 新功能
- `fix:` Bug 修复
- `docs:` 仅文档变更
- `chore:` 工具或配置调整
- `refactor:` 不改变行为的代码重构

示例：

`feat(graph_builder): add retry mechanism for Zep connection failures`

## LLM Compatibility Notes

- backend 支持任意 OpenAI-compatible LLM API。
- 出于成本效果考虑，推荐使用 Bailian Platform 的 Alibaba Qwen-plus。
- 如果你提交与 LLM 相关的改动，请至少使用一个本地或云端 model 进行测试。
- 不要硬编码 model 名称；请统一使用 `LLM_MODEL_NAME` 环境变量。

## Questions?

- GitHub Discussions: <https://github.com/666ghj/MiroFish/discussions>
- Discord: <http://discord.gg/ePf5aPaHnA>
- Email: <mailto:mirofish@shanda.com>
