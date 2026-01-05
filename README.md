<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="MiroFish Logo" width="75%"/>

简洁通用的群体智能引擎，预测万物
</br>
<em>A Simple and Universal Swarm Intelligence Engine, Predicting Anything</em>

<a href="https://www.shanda.com/" target="_blank"><img src="./static/image/shanda_logo.png" alt="666ghj%2MiroFish | Shanda" height="40"/></a>

[![GitHub Stars](https://img.shields.io/github/stars/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/stargazers)
[![GitHub Watchers](https://img.shields.io/github/watchers/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/watchers)
[![GitHub Forks](https://img.shields.io/github/forks/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/network)
[![GitHub Issues](https://img.shields.io/github/issues/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/issues)
[![GitHub Pull Requests](https://img.shields.io/github/issues-pr/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/pulls)

[![GitHub License](https://img.shields.io/github/license/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/blob/main/LICENSE)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/666ghj/MiroFish)
[![Version](https://img.shields.io/badge/version-v0.2.0--beta-orange.svg?style=flat-square)](https://github.com/666ghj/MiroFish)

[English](./README-EN.md) | [中文文档](./README.md)

</div>

---

## 🆕 v0.2.0-beta 新特性（开发预览版）

> ⚠️ **注意**: 这是开发预览版本，功能可能不稳定，仅供测试和反馈使用。
>
> 本版本新增：历史记录页面、报告断点续跑、Interview 环境保活/安全激活、OpenAI 原生工具调用、LLM 模型设置、一键烟测脚本。详细说明见 [`docs/UPDATES.md`](./docs/UPDATES.md)。

### 主要更新

| 特性 | 说明 |
|------|------|
| **History 页面** | 新增 `/history` 路由，按 Project → Simulation → Report 嵌套关系浏览历史记录，支持一键跳转 |
| **报告断点续跑** | `Continue` 从未完成章节继续生成；`Regenerate` 创建新报告（旧报告保留在历史中） |
| **Interview 环境保活** | 模拟完成后自动进入 waiting 模式，支持后续报告生成时的 Agent 采访 |
| **安全激活** | 当旧环境不可恢复时，`Activate (safe)` 自动创建新分支，不破坏原始数据 |
| **代码版本检测** | 自动检测脚本代码更新，必要时重启模拟进程以使用新代码 |
| **OpenAI 原生工具调用** | ReportAgent 使用 OpenAI `tool_calls` 替代文本解析，提高稳定性 |
| **LLM 模型设置** | 新增 Settings 页面，支持模型列表查看、切换和配置 |
| **一键烟测** | `npm run smoke` 快速验证端到端流程（project → graph → simulation → report） |

### 使用说明

```bash
# 启动服务
npm run dev

# 烟测（Quick，非破坏性）
npm run smoke

# 烟测（Full，会创建新 project/simulation/report）
npm run smoke:full
```

更多详情请参阅 [`docs/UPDATES.md`](./docs/UPDATES.md)。

---

## ⚡ 项目概述

**MiroFish** 是一款基于多智能体技术的新一代 AI 预测引擎。通过提取现实世界的种子信息（如突发新闻、政策草案、金融信号），自动构建出高保真的平行数字世界。在此空间内，成千上万个具备独立人格、长期记忆与行为逻辑的智能体进行自由交互与社会演化。你可透过「上帝视角」动态注入变量，精准推演未来走向——**让未来在数字沙盘中预演，助决策在百战模拟后胜出**。

> 你只需：上传种子材料（数据分析报告或者有趣的小说故事），并用自然语言描述预测需求</br>
> MiroFish 将返回：一份详尽的预测报告，以及一个可深度交互的高保真数字世界

### 我们的愿景

MiroFish 致力于打造映射现实的群体智能镜像，通过捕捉个体互动引发的群体涌现，突破传统预测的局限：

- **于宏观**：我们是决策者的预演实验室，让政策与公关在零风险中试错
- **于微观**：我们是个人用户的创意沙盘，无论是推演小说结局还是探索脑洞，皆可有趣、好玩、触手可及

从严肃预测到趣味仿真，我们让每一个如果都能看见结果，让预测万物成为可能。

## 🎬 演示视频


<div align="center">
<a href="https://www.bilibili.com/video/BV1VYBsBHEMY/" target="_blank"><img src="./static/image/武大模拟演示封面.png" alt="MiroFish Demo Video" width="75%"/></a>

点击图片查看使用微舆BettaFish生成的《武大舆情报告》进行预测的完整演示视频
</div>

> 红楼梦结局模拟推演演示视频、金融方向预测示例演示视频等陆续更新中...

## 🔄 工作流程

1. **图谱构建**：现实种子提取 & 个体与群体记忆注入 & GraphRAG构建
2. **环境搭建**：实体关系抽取 & 人设生成 & 环境配置Agent注入仿真参数
3. **开始模拟**：双平台并行模拟 & 自动解析预测需求 & 动态更新时序记忆
4. **报告生成**：ReportAgent拥有丰富的工具集与模拟后环境进行深度交互
5. **深度互动**：与模拟世界中的任意一位进行对话 & 与ReportAgent进行对话

## 🚀 快速开始

### 前置要求

> 注：MiroFish在Mac环境下完成开发与测试，Windows兼容性未知，测试中

| 工具 | 版本要求 | 说明 | 安装检查 |
|------|---------|------|---------|
| **Node.js** | 18+ | 前端运行环境，包含 npm | `node -v` |
| **Python** | 3.11+ | 后端运行环境 | `python --version` |
| **uv** | 最新版 | Python 包管理器 | `uv --version` |

### 1. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入必要的 API 密钥
```

**必需的环境变量：**

```env
# LLM API配置（支持 OpenAI SDK 格式的任意 LLM）
# 推荐使用阿里百炼平台qwen-plus模型：https://bailian.console.aliyun.com/
# 注意消耗较大，可先进行小于40轮的模拟尝试
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Zep Cloud 配置
# 每月免费额度即可支撑简单使用：https://app.getzep.com/
ZEP_API_KEY=your_zep_api_key
```

### 2. 安装依赖

```bash
# 一键安装所有依赖（根目录 + 前端 + 后端）
npm run setup:all
```

或者分步安装：

```bash
# 安装 Node 依赖（根目录 + 前端）
npm run setup

# 安装 Python 依赖（自动创建虚拟环境）
npm run setup:backend
```

### 3. 启动服务

```bash
# 同时启动前后端（在项目根目录执行）
npm run dev
```

**服务地址：**
- 前端：`http://localhost:3000`
- 后端 API：`http://localhost:5001`

**单独启动：**

```bash
npm run backend   # 仅启动后端
npm run frontend  # 仅启动前端
```

## 📄 致谢

**MiroFish 得到了盛大集团的战略支持和孵化！**

MiroFish 的核心仿真引擎由 **[OASIS](https://github.com/camel-ai/oasis)** 驱动。OASIS 是由 [CAMEL-AI](https://github.com/camel-ai) 团队开发的高性能社交媒体模拟框架，支持百万级智能体交互仿真，为 MiroFish 的群体智能涌现提供了坚实的技术基础。我们衷心感谢 CAMEL-AI 团队的开源贡献！

## 📈 项目统计

<a href="https://www.star-history.com/#666ghj/MiroFish&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&legend=top-left" />
 </picture>
</a>
