FROM python:3.11

# 安装 Node.js （满足 >=18）及必要工具
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# 从 uv 官方镜像复制 uv
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# 先复制依赖描述文件以利用缓存
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# 安装依赖（Node + Python）
RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync --frozen

# 复制项目源码
COPY . .

# C2：前端 API Key 是 Vite 构建期变量，必须在 `npm run build` 之前进入构建环境，否则打包后的
# UI 带空 key、在 AUTH_ENABLED=true 下所有 /api/* 会 401。由 docker compose 经 build-arg 注入。
ARG VITE_API_KEY=""
ENV VITE_API_KEY=$VITE_API_KEY

# C1：构建前端静态产物，生产用 `vite preview` 提供（不再运行 Vite 开发服务器）
RUN npm run build

EXPOSE 3000 5001

# C1：生产启动 —— 后端用 gunicorn（单 worker 多线程，保留进程内模拟态），
# 前端用 vite preview 提供已构建产物。开发请改用 `npm run dev`。
# 安全前提：须经 .env 设置 SECRET_KEY 与 API_KEY（FLASK_DEBUG 默认 false）。
CMD ["npm", "run", "start"]