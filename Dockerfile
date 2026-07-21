FROM node:22.12.0-bookworm-slim AS node_runtime

FROM python:3.11-bookworm
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

# 复制完整 Node.js 运行时目录，保留 npm/npx/corepack 的内部链接关系
COPY --from=node_runtime /usr/local/ /usr/local/
RUN pip install --upgrade pip
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

EXPOSE 3000 5001

# 同时启动前后端（开发模式）
CMD ["npm", "run"]
