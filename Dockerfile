# MiroFish production Dockerfile for agent.profikid.nl deployment
# - Builds the Vue frontend into static files
# - Serves the static bundle via nginx on :3000
# - Reverse-proxies /api/* to the Flask backend on :5001 (same container, localhost)
# - Single exposed port for Traefik
# - Memory graph: Graphiti (Python lib) talks to FalkorDB on the shared network

FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VITE_API_BASE_URL=""  \
    HF_HUB_OFFLINE=0 \
    SENTENCE_TRANSFORMERS_HOME=/root/.cache/huggingface

# Install Node 20 (for building the frontend), nginx (for serving it), and
# build deps for the Python wheels (sentence-transformers pulls numpy/torch).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        nodejs \
        npm \
        nginx \
        curl \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# ---- 1) Install Python deps (backend) ----
# Copy the local path-dep (camel-oasis fork) BEFORE uv sync, so the path can resolve.
# Note: we don't COPY uv.lock here — the first build has to generate it. Once a
# successful build has happened, the lock will be in the source tree and a
# subsequent `uv sync --frozen` will be reproducible.
COPY backend/vendor ./backend/vendor
COPY backend/pyproject.toml ./backend/
WORKDIR /app/backend
RUN uv sync

# ---- 2) Install Node deps + build frontend ----
WORKDIR /app

# Copy locales first because the Vite build's `@locales` alias points to ../locales
COPY locales/ ./locales/

COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --no-audit --no-fund

# Copy full frontend source and build the production bundle
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# ---- 3) Copy the rest of the app (backend source) ----
COPY backend/ ./backend/

# ---- 4) Pre-download the sentence-transformers embedding model ----
# Doing it at build time means the container is ready to serve on first boot
# (no 100MB download the first time the user runs a graph build).
WORKDIR /app/backend
RUN uv run python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')" \
    || (echo 'Failed to pre-download embedding model — build will fall back to download on first use.' && exit 0)

# ---- 5) nginx config + start script ----
COPY nginx.conf /etc/nginx/nginx.conf
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Runtime dirs
RUN mkdir -p /app/backend/uploads /app/logs /var/lib/nginx /var/log/nginx

EXPOSE 3000

CMD ["/app/start.sh"]
