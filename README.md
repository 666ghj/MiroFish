<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="MiroFish Logo" width="75%"/>

<a href="https://trendshift.io/repositories/16144" target="_blank"><img src="https://trendshift.io/api/badge/repositories/16144" alt="666ghj%2FMiroFish | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

简洁通用的群体智能引擎，预测万物
</br>
<em>A Simple and Universal Swarm Intelligence Engine, Predicting Anything</em>

<a href="https://www.shanda.com/" target="_blank"><img src="./static/image/shanda_logo.png" alt="666ghj%2FMiroFish | Shanda" height="40"/></a>

[![GitHub Stars](https://img.shields.io/github/stars/666ghj/MiroFish?style=flat-square&color=DAA520)](https://github.com/666ghj/MiroFish/stargazers)
[![GitHub Watchers](https://img.shields.io/github/watchers/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/watchers)
[![GitHub Forks](https://img.shields.io/github/forks/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/network)
[![Docker](https://img.shields.io/badge/Docker-Build-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/666ghj/MiroFish)

[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](http://discord.gg/ePf5aPaHnA)
[![X](https://img.shields.io/badge/X-Follow-000000?style=flat-square&logo=x&logoColor=white)](https://x.com/mirofish_ai)
[![Instagram](https://img.shields.io/badge/Instagram-Follow-E4405F?style=flat-square&logo=instagram&logoColor=white)](https://www.instagram.com/mirofish_ai/)

[English](./README.md) | [中文文档](./README-ZH.md)

</div>

## ⚡ Overview

**MiroFish** is a next-generation AI prediction engine powered by multi-agent technology. By extracting seed information from the real world (such as breaking news, policy drafts, or financial signals), it automatically constructs a high-fidelity parallel digital world. Within this space, thousands of intelligent agents with independent personalities, long-term memory, and behavioral logic freely interact and undergo social evolution. You can inject variables dynamically from a "God's-eye view" to precisely deduce future trajectories — **rehearse the future in a digital sandbox, and win decisions after countless simulations**.

> You only need to: Upload seed materials (data analysis reports or interesting novel stories) and describe your prediction requirements in natural language</br>
> MiroFish will return: A detailed prediction report and a deeply interactive high-fidelity digital world

### Our Vision

MiroFish is dedicated to creating a swarm intelligence mirror that maps reality. By capturing the collective emergence triggered by individual interactions, we break through the limitations of traditional prediction:

- **At the Macro Level**: We are a rehearsal laboratory for decision-makers, allowing policies and public relations to be tested at zero risk
- **At the Micro Level**: We are a creative sandbox for individual users — whether deducing novel endings or exploring imaginative scenarios, everything can be fun, playful, and accessible

From serious predictions to playful simulations, we let every "what if" see its outcome, making it possible to predict anything.

## 🌐 Live Demo

Welcome to visit our online demo environment and experience a prediction simulation on trending public opinion events we've prepared for you: [mirofish-live-demo](https://666ghj.github.io/mirofish-demo/)

## 📸 Screenshots

<div align="center">
<table>
<tr>
<td><img src="./static/image/Screenshot/运行截图1.png" alt="Screenshot 1" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图2.png" alt="Screenshot 2" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/image/Screenshot/运行截图3.png" alt="Screenshot 3" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图4.png" alt="Screenshot 4" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/image/Screenshot/运行截图5.png" alt="Screenshot 5" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图6.png" alt="Screenshot 6" width="100%"/></td>
</tr>
</table>
</div>

## 🎬 Demo Videos

### 1. Wuhan University Public Opinion Simulation + MiroFish Project Introduction

<div align="center">
<a href="https://www.bilibili.com/video/BV1VYBsBHEMY/" target="_blank"><img src="./static/image/武大模拟演示封面.png" alt="MiroFish Demo Video" width="75%"/></a>

Click the image to watch the complete demo video for prediction using BettaFish-generated "Wuhan University Public Opinion Report"
</div>

### 2. Dream of the Red Chamber Lost Ending Simulation

<div align="center">
<a href="https://www.bilibili.com/video/BV1cPk3BBExq" target="_blank"><img src="./static/image/红楼梦模拟推演封面.jpg" alt="MiroFish Demo Video" width="75%"/></a>

Click the image to watch MiroFish's deep prediction of the lost ending based on hundreds of thousands of words from the first 80 chapters of "Dream of the Red Chamber"
</div>

> **Financial Prediction**, **Political News Prediction** and more examples coming soon...

## 🔄 Workflow

1. **Graph Building**: Seed extraction & Individual/collective memory injection & GraphRAG construction
2. **Environment Setup**: Entity relationship extraction & Persona generation & Agent configuration injection
3. **Simulation**: Dual-platform parallel simulation & Auto-parse prediction requirements & Dynamic temporal memory updates
4. **Report Generation**: ReportAgent with rich toolset for deep interaction with post-simulation environment
5. **Deep Interaction**: Chat with any agent in the simulated world & Interact with ReportAgent

## 🚀 Quick Start

### Option 1: Source Code Deployment (Recommended)

#### Prerequisites

| Tool | Version | Description | Check Installation |
|------|---------|-------------|-------------------|
| **Node.js** | 18+ | Frontend runtime, includes npm | `node -v` |
| **Python** | ≥3.11 | Backend runtime. Python 3.13 is supported for the API and local graph backend. | `python --version` |
| **Python 3.11** | 3.11.x | Optional but recommended for OASIS/CAMEL, because `camel-oasis==0.2.5` declares Python `<3.12`. | `python3.11 --version` |

#### 1. Configure Environment Variables

```bash
# Copy the example configuration file
cp .env.example .env

# Edit the .env file and fill in the required API keys
```

**Required Environment Variables:**

```env
# LLM API Configuration (supports any LLM API with OpenAI SDK format)
# Recommended: Alibaba Qwen-plus model via Bailian Platform: https://bailian.console.aliyun.com/
# High consumption, try simulations with fewer than 40 rounds first
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
LLM_CONTEXT_WINDOW=8192
LLM_MAX_CONCURRENCY=1
LLM_JSON_MAX_RETRIES=2
ONTOLOGY_MAX_OUTPUT_TOKENS=2048
ONTOLOGY_PROMPT_MARGIN_TOKENS=512
LOCAL_ZEP_EXTRACT_MAX_OUTPUT_TOKENS=2048
LOCAL_ZEP_EXTRACT_MAX_RETRIES=2

# Local Graph / Embeddings Configuration
# Use an OpenAI-compatible embeddings endpoint. vLLM is a good first option.
EMBEDDING_API_KEY=local-embedding-key
EMBEDDING_BASE_URL=http://localhost:8001/v1
EMBEDDING_MODEL_NAME=your_embedding_model

# Optional cross-encoder reranker endpoint. If omitted, local graph search falls back to RRF.
RERANKER_API_KEY=local-reranker-key
RERANKER_BASE_URL=http://localhost:8002/v1
RERANKER_MODEL_NAME=your_reranker_model
LOCAL_ZEP_RERANK_TOP_K=50

# Optional: choose where the local graph SQLite file is stored
LOCAL_ZEP_DB_PATH=backend/data/local_zep.sqlite3

# Optional: use a separate Python 3.11 venv for original OASIS/CAMEL scripts
OASIS_PYTHON=/absolute/path/to/venv11/bin/python
```

#### 2. Install Dependencies

```bash
# One-click installation of all dependencies (root + frontend + backend)
npm run setup:all
```

Or install step by step:

```bash
# Install Node dependencies (root + frontend)
npm run setup

# Install Python dependencies (backend, auto-creates virtual environment)
npm run setup:backend
```

If your default `python3` is older than 3.11, create the backend venv manually with the desired interpreter before running the backend:

```bash
python3.13 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r backend/requirements.txt
```

For the original OASIS/CAMEL simulation engine, use a Python 3.11 venv and point `OASIS_PYTHON` at it:

```bash
python3.11 -m venv venv11
./venv11/bin/python -m pip install --upgrade pip
./venv11/bin/python -m pip install -r backend/requirements.txt
echo "OASIS_PYTHON=$(pwd)/venv11/bin/python" >> .env
```

#### 3. Start Services

```bash
# Start both frontend and backend (run from project root)
npm run dev
```

**Service URLs:**
- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:5001`

**Start Individually:**

```bash
npm run backend   # Start backend only
npm run frontend  # Start frontend only
```

### Local Model Runtime and Parameters

MiroFish no longer requires Zep Cloud. The local graph module stores graph data in SQLite and uses your OpenAI-compatible embedding endpoint. A reranker endpoint is optional and is used only when graph search requests `cross_encoder`; otherwise search falls back to local hybrid ranking/RRF.

Example local endpoints:

```bash
# Main LLM endpoint, llama.cpp example
llama-server \
  -m /path/to/model.gguf \
  --alias Qwen3.5-9B-VL \
  --host 127.0.0.1 \
  --port 8000 \
  -c 16384 \
  --jinja

# Embeddings endpoint, vLLM example
vllm serve /path/to/Qwen3-Embedding-0.6B \
  --host 127.0.0.1 \
  --port 8001 \
  --runner pooling \
  --max-model-len 8192

# Optional reranker endpoint, vLLM example
vllm serve /path/to/Qwen3-Reranker-0.6B \
  --host 127.0.0.1 \
  --port 8002 \
  --runner pooling \
  --max-model-len 8192
```

Tested 24GB GPU profile (RTX 3090 / RTX 4090 class). Paths are intentionally anonymized:

```bash
# Main llama.cpp LLM endpoint
./llama-server \
  --mmproj /path/to/models/Qwen3.5-9B-gguf/mmproj-Qwen3.5-9B-BF16.gguf \
  --alias Qwen3.5-9B-VL \
  --host 127.0.0.1 \
  --port 8000 \
  -c 280000 \
  -ngl auto \
  --temp 0.7 \
  --top-p 0.8 \
  --top-k 20 \
  --min-p 0.0 \
  --jinja \
  -m /path/to/models/Qwen3.5-9B-gguf/Qwen3.5-9B-Q6_K.gguf

# Embedding endpoint. Observed peak is about 2-3GB VRAM.
vllm serve /path/to/models/embedding/Qwen3-Embedding-0.6B \
  --host 127.0.0.1 \
  --port 8001 \
  --runner pooling \
  --gpu-memory-utilization 0.08 \
  --max-model-len 8192 \
  --quantization fp8 \
  --kv-cache-dtype fp8

# Reranker endpoint. Observed peak is about 2-3GB VRAM.
vllm serve /path/to/models/embedding/Qwen3-Reranker-0.6B \
  --host 127.0.0.1 \
  --port 8002 \
  --runner pooling \
  --gpu-memory-utilization 0.09 \
  --max-model-len 8192 \
  --quantization fp8 \
  --kv-cache-dtype fp8
```

Matching `.env` settings:

```env
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_MODEL_NAME=Qwen3.5-9B-VL
LLM_CONTEXT_WINDOW=280000
LLM_MAX_CONCURRENCY=1
ONTOLOGY_MAX_OUTPUT_TOKENS=8192
LOCAL_ZEP_EXTRACT_MAX_OUTPUT_TOKENS=8192

EMBEDDING_BASE_URL=http://127.0.0.1:8001/v1
EMBEDDING_MODEL_NAME=/path/to/Qwen3-Embedding-0.6B

RERANKER_BASE_URL=http://127.0.0.1:8002/v1
RERANKER_MODEL_NAME=/path/to/Qwen3-Reranker-0.6B
LOCAL_ZEP_RERANK_TOP_K=50
```

Parameter rules:
- `LLM_CONTEXT_WINDOW` must match the context length exposed by the main LLM server. Keep `prompt tokens + max output tokens <= LLM_CONTEXT_WINDOW`.
- For the 24GB profile above, set `LLM_CONTEXT_WINDOW=280000` to match `-c 280000`. For a `16k` context model, `ONTOLOGY_MAX_OUTPUT_TOKENS=8192` leaves roughly half the window for output. For an `8k` endpoint, use `2048` to `4096`.
- Set `LLM_MAX_CONCURRENCY=1` for single llama.cpp/vLLM main endpoints unless you know the server can handle parallel chat completions.
- Embedding dimension is not configured manually. The local graph records vectors from the embedding model; keep the same embedding model for one graph database.
- The reranker is different from the embedding model. Embeddings are required for graph indexing and semantic search. The reranker is optional and only reorders candidate search results.
- `.env`, `start.sh`, `venv/`, `venv11/`, uploaded simulations, and local graph databases are intentionally ignored by git.

### Tailscale Access

Release note: Tailscale support is intended for source-code/dev deployments where the backend and Vite proxy run on the same host. It does not make the local LLM, embedding, or reranker endpoints public by itself; keep those endpoints bound to `127.0.0.1` unless you intentionally expose them.

The frontend now defaults to same-origin `/api` instead of `http://localhost:5001`, so opening the Vite dev server from another device over Tailscale will still reach the backend running on the host machine.

Recommended root `.env` settings:

```env
VITE_DEV_HOST=0.0.0.0
VITE_DEV_PORT=3000
VITE_DEV_PROXY_TARGET=http://127.0.0.1:5001
VITE_ALLOWED_HOSTS=localhost,127.0.0.1,.ts.net,.beta.tailscale.net
FLASK_HOST=0.0.0.0
FLASK_PORT=5001
```

Then access from another Tailscale device at:

- Frontend: `http://<your-tailnet-hostname>:3000`
- Backend: `http://<your-tailnet-hostname>:5001`

If you expose the backend through `tailscale serve` or `tailscale funnel`, set `ENABLE_PROXY_FIX=true`. If HMR does not reconnect correctly over MagicDNS, set `VITE_HMR_HOST` to your Tailscale hostname.

### Option 2: Docker Deployment

Release constraint: Docker deployment is legacy/not validated for the local Zep replacement, external vLLM/llama.cpp endpoints, and split Python 3.11 OASIS runtime. Use source deployment for the tested local-first workflow.

```bash
# 1. Configure environment variables (same as source deployment)
cp .env.example .env

# 2. Pull image and start
docker compose up -d
```

Reads `.env` from root directory by default, maps ports `3000 (frontend) / 5001 (backend)`

> Mirror address for faster pulling is provided as comments in `docker-compose.yml`, replace if needed.

## 📬 Join the Conversation

<div align="center">
<img src="./static/image/QQ群.png" alt="QQ Group" width="60%"/>
</div>

&nbsp;

The MiroFish team is recruiting full-time/internship positions. If you're interested in multi-agent simulation and LLM applications, feel free to send your resume to: **mirofish@shanda.com**

## 📄 Acknowledgments

**MiroFish has received strategic support and incubation from Shanda Group!**

MiroFish's simulation engine is powered by **[OASIS (Open Agent Social Interaction Simulations)](https://github.com/camel-ai/oasis)**, We sincerely thank the CAMEL-AI team for their open-source contributions!

## 📈 Project Statistics

<a href="https://github.com/666ghj/MiroFish">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="static/image/star-history-dark.svg" />
   <source media="(prefers-color-scheme: light)" srcset="static/image/star-history-light.svg" />
   <img alt="666ghj/MiroFish Star History Chart" src="static/image/star-history-light.svg" />
 </picture>
</a>
