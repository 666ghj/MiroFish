# MiroFish Docker 部署指南

本文档介绍如何使用 Docker 和 Docker Compose 部署 MiroFish 项目。

## 前置要求

- Docker 20.10+
- Docker Compose 2.0+

## 部署模式

MiroFish 支持两种部署模式：

| 模式 | 配置文件 | 适用场景 | 镜像来源 |
|------|---------|---------|---------|
| **本地构建** | `docker-compose.yml` | 开发、测试 | 从源代码构建 |
| **云端镜像** | `docker-compose.pull.yml` | 生产环境 | 从 GHCR 拉取 |

---

## 快速开始

### 1. 配置环境变量

复制环境变量示例文件并填入必要的 API 密钥：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入以下必需的环境变量：

```env
# LLM API配置
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus

# Zep Cloud 配置
ZEP_API_KEY=your_zep_api_key_here
```

### 2. 选择部署模式

#### 模式 A：本地构建（开发）

```bash
# 构建镜像并启动所有服务
docker-compose up -d --build

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f
```

#### 模式 B：云端镜像（生产）

```bash
# 拉取最新镜像并启动
docker-compose -f docker-compose.pull.yml up -d

# 拉取指定版本
IMAGE_TAG=-latest-backend-20250114-abc123 docker-compose -f docker-compose.pull.yml up -d

# 先拉取镜像再启动
docker-compose -f docker-compose.pull.yml pull
docker-compose -f docker-compose.pull.yml up -d
```

### 3. 访问应用

- 前端：http://localhost
- 后端 API：http://localhost:5001

---

## GitHub Actions 自动构建

项目配置了 GitHub Actions 工作流，自动构建并推送 Docker 镜像到 GitHub Container Registry (GHCR)。

### 触发条件

- **推送到 main 分支**：构建并推送稳定版本镜像
- **创建 Pull Request**：构建并推送 PR 测试镜像
- **推送 Git Tag**：构建并推送版本标签镜像

### 工作流文件

- `.github/workflows/docker-build.yml` - Docker 构建工作流

### 构建产物

镜像推送到：`ghcr.io/deroino/mirofish`

### 镜像标签说明

| 标签格式 | 说明 | 示例 |
|---------|------|------|
| `latest-backend` | 最新后端（仅主分支） | `ghcr.io/deroino/mirofish:latest-backend` |
| `latest-frontend` | 最新前端（仅主分支） | `ghcr.io/deroino/mirofish:latest-frontend` |
| `stable-backend-YYYYMMDD-SHA` | 稳定版本 | `ghcr.io/deroino/mirofish:stable-backend-20250114-abc123` |
| `stable-frontend-YYYYMMDD-SHA` | 稳定版本 | `ghcr.io/deroino/mirofish:stable-frontend-20250114-abc123` |
| `gha-backend-RUN_ID` | PR 构建标签 | `ghcr.io/deroino/mirofish:gha-backend-123456` |
| `gha-frontend-RUN_ID` | PR 构建标签 | `ghcr.io/deroino/mirofish:gha-frontend-123456` |

### 查看构建状态

访问 GitHub Actions 页面查看构建状态和日志：
```
https://github.com/Deroino/MiroFish/actions
```

---

## 常用命令

### 服务管理

```bash
# 本地构建模式
docker-compose up -d
docker-compose down
docker-compose restart
docker-compose ps

# 云端镜像模式
docker-compose -f docker-compose.pull.yml up -d
docker-compose -f docker-compose.pull.yml down
docker-compose -f docker-compose.pull.yml restart
docker-compose -f docker-compose.pull.yml ps
```

### 日志查看

```bash
# 查看所有服务日志
docker-compose logs -f

# 查看后端日志
docker-compose logs -f backend

# 查看前端日志
docker-compose logs -f frontend

# 查看最近 100 行日志
docker-compose logs --tail=100
```

### 构建相关

```bash
# 重新构建镜像
docker-compose build

# 重新构建并启动
docker-compose up -d --build

# 强制重新构建（不使用缓存）
docker-compose build --no-cache
```

### 镜像操作

```bash
# 拉取最新镜像
docker pull ghcr.io/deroino/mirofish:latest-backend
docker pull ghcr.io/deroino/mirofish:latest-frontend

# 拉取指定版本
docker pull ghcr.io/deroino/mirofish:stable-backend-20250114-abc123
docker pull ghcr.io/deroino/mirofish:stable-frontend-20250114-abc123

# 查看本地镜像
docker images | grep mirofish
```

### 进入容器

```bash
# 进入后端容器
docker-compose exec backend sh

# 进入前端容器
docker-compose exec frontend sh
```

---

## 项目结构

```
MiroFish/
├── Dockerfile                      # 多阶段构建配置
├── docker-compose.yml              # 本地构建模式配置
├── docker-compose.pull.yml         # 云端镜像模式配置
├── .dockerignore                   # Docker 构建忽略文件
├── .github/
│   └── workflows/
│       └── docker-build.yml        # GitHub Actions 构建工作流
├── docker/
│   └── nginx.conf                  # Nginx 配置文件
├── backend/                        # 后端源代码
│   ├── app/
│   ├── requirements.txt
│   └── run.py
└── frontend/                       # 前端源代码
    ├── src/
    └── package.json
```

---

## Dockerfile 说明

本项目采用多阶段构建策略：

### 阶段 1: frontend-builder
- 基于 `node:18-alpine`
- 构建前端应用（Vite + Vue 3）
- 产出：构建产物在 `/app/frontend/dist`

### 阶段 2: backend
- 基于 `python:3.12-slim`
- 使用 uv 安装 Python 依赖
- 运行 Flask 后端服务
- 暴露端口：5001

### 阶段 3: frontend
- 基于 `nginx:alpine`
- 使用 Nginx 提供静态文件服务
- 反向代理后端 API
- 暴露端口：80

---

## 端口映射

| 服务 | 容器端口 | 宿主机端口 | 说明 |
|------|---------|-----------|------|
| backend | 5001 | 5001 | Flask 后端 API |
| frontend | 80 | 80 | Nginx 前端服务 |

---

## 数据持久化

当前配置中，后端数据目录挂载到 `./backend/data`，可根据需要调整：

```yaml
volumes:
  - ./backend/data:/app/data
```

---

## 健康检查

- **后端**：每 30 秒检查 `http://localhost:5001/health`
- **前端**：每 30 秒检查 `http://localhost/`

服务启动后会等待健康检查通过后才标记为可用。

---

## 网络配置

所有服务运行在 `mirofish-network` 网络中，可以通过服务名互相访问：

- 后端服务名：`mirofish-backend`
- 前端服务名：`mirofish-frontend`

---

## 故障排查

### 服务无法启动

```bash
# 查看详细日志
docker-compose logs backend
docker-compose logs frontend

# 检查环境变量配置
docker-compose config
```

### 健康检查失败

```bash
# 手动检查健康端点
docker-compose exec backend curl http://localhost:5001/health

# 查看后端日志
docker-compose logs backend
```

### 构建失败

```bash
# 清理缓存重新构建
docker-compose build --no-cache

# 清理所有 Docker 资源（谨慎使用）
docker system prune -a
```

### 镜像拉取失败

```bash
# 检查镜像是否存在
docker pull ghcr.io/deroino/mirofish:latest-backend

# 登录 GHCR（如果需要）
echo $GITHUB_TOKEN | docker login ghcr.io -u $GITHUB_USER --password-stdin
```

### 端口冲突

如果端口被占用，可以修改 `docker-compose.yml` 或 `docker-compose.pull.yml` 中的端口映射：

```yaml
ports:
  - "8080:80"    # 前端改为 8080
  - "5002:5001"  # 后端改为 5002
```

---

## 生产环境建议

1. **使用版本标签**：使用 stable 标签而非 latest
   ```bash
   IMAGE_TAG=-stable-backend-20250114-abc123 docker-compose -f docker-compose.pull.yml up -d
   ```

2. **配置资源限制**：在 docker-compose 文件中添加资源限制
   ```yaml
   deploy:
     resources:
       limits:
         cpus: '2'
         memory: 2G
       reservations:
         cpus: '1'
         memory: 1G
   ```

3. **使用环境变量文件**：确保 `.env` 文件不提交到版本控制

4. **配置日志轮转**：防止日志文件过大
   ```yaml
   logging:
     driver: "json-file"
     options:
       max-size: "10m"
       max-file: "3"
   ```

5. **启用 HTTPS**：使用 Nginx SSL 配置

6. **定期更新镜像**：
   ```bash
   docker-compose -f docker-compose.pull.yml pull
   docker-compose -f docker-compose.pull.yml up -d
   ```

---

## 多平台支持

Docker 镜像支持以下平台：
- `linux/amd64`
- `linux/arm64`

---

## 许可证

本项目遵循 AGPL-3.0 许可证。