FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app/backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --extra graphiti --no-dev

COPY backend/ ./

EXPOSE 5001

CMD [".venv/bin/python", "run.py"]
