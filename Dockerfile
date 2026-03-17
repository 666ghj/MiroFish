# ---- Build stage ----
FROM python:3.11-slim AS backend-deps

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# ---- Frontend build stage ----
FROM node:18-slim AS frontend-build

WORKDIR /app
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci && npm ci --prefix frontend

COPY frontend/ ./frontend/
RUN npm run --prefix frontend build

# ---- Production stage ----
FROM python:3.11-slim

# Install Node.js for serving (minimal) and curl for healthcheck
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm curl \
  && npm install -g serve \
  && apt-get purge -y npm \
  && apt-get autoremove -y \
  && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r mirofish && useradd -r -g mirofish -m mirofish

WORKDIR /app

# Copy backend dependencies and source
COPY --from=backend-deps /app/backend/.venv /app/backend/.venv
COPY backend/ ./backend/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Copy root files needed for startup
COPY package.json ./

# Create uploads directory with correct permissions
RUN mkdir -p backend/uploads && chown -R mirofish:mirofish /app

USER mirofish

EXPOSE 3000 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:5001/health || exit 1

# Start both backend and frontend static server
CMD ["sh", "-c", "cd backend && .venv/bin/python run.py & serve -s /app/frontend/dist -l 3000 & wait"]
