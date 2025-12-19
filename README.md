<p align="center">
  <img src="./static/image/MiroFish_logo_compressed.jpeg" alt="MiroFish Logo" width="70%"/>
</p>

<p align="center">
  <strong>简洁通用的群体智能引擎，预测万物</strong>
  <br />
  <em>A Simple and Universal Swarm Intelligence Engine, Predicting Anything</em>
</p>

## ⚡ 项目概述

**MiroFish** 是一款基于多智能体技术的新一代 AI 预测引擎。通过提取现实世界的种子信息（如突发新闻、政策草案、金融信号），自动构建出高保真的平行数字世界。在此空间内，成千上万个具备独立人格、长期记忆与行为逻辑的智能体进行自由交互与社会演化。你可透过「上帝视角」动态注入变量，精准推演未来走向——**让未来在数字沙盘中预演，助决策在百战模拟后胜出**。

> 你只需：上传一份或多份「种子材料」（舆情分析报告、量化分析报告，甚至有趣的小说故事），并用自然语言描述你的模拟/预测需求
> MiroFish 将返回：一份详尽的模拟/预测报告，以及一个可深度交互、可按你意愿持续推演的高保真数字世界

#### 我们的愿景

MiroFish 致力于打造映射现实的群体智能镜像，通过捕捉个体互动引发的「群体涌现」，突破传统预测的局限：

- **于宏观**：我们是决策者的预演实验室，让政策与公关在零风险中试错
- **于微观**：我们是个人用户的创意沙盘，无论是推演小说结局还是探索脑洞，皆可有趣、好玩、触手可及

从严肃预测到趣味仿真，我们让每一个「如果」都能看见结果，让**预测万物**成为可能。

## 🎬 演示视频-待上传

1. 针对微舆BettaFish生成的武大舆情报告进行预测的完整演示视频
2. 红楼梦结局预测完整演示视频
3. 金融方向的预测完整演示视频

## 🚀 快速开始

### 前置要求

| 工具 | 版本要求 | 说明 | 安装检查 |
|------|---------|------|---------|
| **Node.js** | 18+ | 前端运行环境，包含 npm | `node -v` |
| **Python** | 3.11+ | 后端运行环境 | `python --version` |
| **uv** | 最新版 | Python 包管理器（替代 pip） | `uv --version` |

### 1. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入必要的 API 密钥
```

**必需的环境变量：**

```env
# LLM API配置（支持 OpenAI SDK 格式的任意 LLM）
# 推荐使用阿里百炼平台Qwen-plus模型：https://bailian.console.aliyun.com/
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Zep Cloud 配置
# 每月免费额度即可支撑使用：https://app.getzep.com/
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
