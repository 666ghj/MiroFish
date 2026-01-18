# ===========================================
# MiroFish Dockerfile - 多阶段构建（优化版）
# ===========================================
# 构建顺序：前端构建 -> 后端镜像 + 前端镜像
# 优化目标：减少镜像大小，清理不必要的文件
# ===========================================

# ===========================================
# 阶段 1: 前端构建
# ===========================================
FROM node:20-alpine AS frontend-builder

# 设置工作目录
WORKDIR /app/frontend

# 复制前端依赖配置
COPY frontend/package*.json ./

# 安装依赖（包括 devDependencies，vite 在 devDependencies 中）
RUN npm ci

# 复制前端源代码
COPY frontend/ ./

# 接收构建参数 API_BASE_URL
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# 构建前端应用
RUN npm run build

# ===========================================
# 阶段 2: 后端依赖安装（构建阶段）
# ===========================================
FROM python:3.12-slim AS backend-builder

# 设置工作目录
WORKDIR /app

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv（Python 包管理器）
RUN pip install --no-cache-dir uv

# 复制后端依赖配置
COPY backend/requirements.txt backend/pyproject.toml backend/uv.lock ./

# 使用 uv 安装依赖（创建虚拟环境）
RUN uv sync --frozen --no-dev

# ===========================================
# 阶段 3: 后端运行镜像（精简版）
# ===========================================
FROM python:3.12-slim AS backend

# 设置工作目录
WORKDIR /app

# 只安装运行时需要的依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制虚拟环境
COPY --from=backend-builder /app/.venv /app/.venv

# 复制后端源代码
COPY backend/ ./

# 暴露后端端口
EXPOSE 5001

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5001 \
    PATH="/app/.venv/bin:$PATH"

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5001/health || exit 1

# 启动后端服务（直接使用虚拟环境中的 Python）
CMD ["python", "run.py"]

# ===========================================
# 阶段 4: 前端镜像（Nginx）
# ===========================================
FROM nginx:alpine AS frontend

# 复制自定义 nginx 配置
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf

# 从构建阶段复制构建产物
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html

# 暴露前端端口
EXPOSE 80

# 启动 nginx
CMD ["nginx", "-g", "daemon off;"]