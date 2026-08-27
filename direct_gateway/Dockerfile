FROM python:3.11-slim AS base
WORKDIR /app
ENV PYTHONPATH=/app
COPY direct_gateway/pyproject.toml direct_gateway/uv.lock ./
RUN pip install --no-cache-dir uv

FROM base AS test
RUN uv sync --frozen --extra dev
COPY direct_gateway/app ./app
COPY direct_gateway/tests ./tests
CMD [".venv/bin/pytest", "-q"]

FROM base AS runtime
RUN uv sync --frozen --no-dev
COPY direct_gateway/app ./app
RUN mkdir -p /var/lib/direct-oauth && chmod 700 /var/lib/direct-oauth
EXPOSE 8090
CMD [".venv/bin/gunicorn", "--bind", "0.0.0.0:8090", "--workers", "1", "--threads", "64", "--timeout", "660", "app.server:app"]
