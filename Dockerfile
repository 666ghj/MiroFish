# ─────────────────────────────────────────────
# Stage 1: Build del frontend Vue
# ─────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /build

# Copiar manifests primer per aprofitar la caché de capes Docker
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copiar el codi font i els fitxers de localització compartits
COPY frontend/ ./
COPY locales/ ../locales/

# Build de producció (genera dist/)
RUN npm run build

# ─────────────────────────────────────────────
# Stage 2: Imatge de producció Flask + gunicorn
# ─────────────────────────────────────────────
FROM python:3.11-slim AS production

# Instal·lar uv per gestionar dependències Python
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# Copiar i instal·lar dependències Python (aprofita caché si pyproject.toml no canvia)
COPY backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-dev

# Copiar el codi font del backend i els fitxers compartits
COPY backend/ ./backend/
COPY locales/ ./locales/

# Copiar el frontend compilat al path que Flask utilitza per servir el SPA
COPY --from=frontend-builder /build/dist ./frontend/dist

# Variables d'entorn de producció
ENV FLASK_DEBUG=False \
    FLASK_HOST=0.0.0.0 \
    FLASK_PORT=5001 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5001

# gunicorn: 1 worker (Container Apps escala horitzontalment via rèpliques)
# threads=4 per gestionar concurrència sense multiprocessing
# timeout=120s per a les operacions LLM de llarga durada
CMD ["backend/.venv/bin/gunicorn", \
     "--bind", "0.0.0.0:5001", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "120", \
     "--worker-class", "gthread", \
     "--chdir", "/app/backend", \
     "wsgi:application"]
