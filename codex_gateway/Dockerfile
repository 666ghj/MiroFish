FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    CODEX_HOME=/var/lib/codex

COPY codex_gateway/pyproject.toml codex_gateway/uv.lock ./
RUN uv sync --frozen --no-dev

COPY codex_gateway/ ./

RUN install -d -m 0700 /var/lib/codex /workspace

EXPOSE 8080

CMD [".venv/bin/gunicorn", "--workers", "1", "--threads", "4", "--bind", "0.0.0.0:8080", "app:create_app()"]
