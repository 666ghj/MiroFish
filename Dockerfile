FROM python:3.11

# 安装 Node.js （满足 >=18）及必要工具
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
  && apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# 通过 pip 安装 uv（替代直接拉取 ghcr.io 官方镜像，避免国内网络卡顿）
RUN pip install -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app

# 先复制依赖描述文件以利用缓存
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# 安装依赖（Node + Python），配置国内加速源
RUN npm config set registry https://registry.npmmirror.com \
  && npm ci \
  && npm ci --prefix frontend \
  && cd backend && env UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ uv sync --frozen

# 复制项目源码
COPY . .

EXPOSE 3000 5001

# 同时启动前后端（开发模式）
CMD ["npm", "run", "dev"]