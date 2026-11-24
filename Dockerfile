FROM python:3.11

# Install Node.js (>=18) and required tools
RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

# Copy uv from the official uv image
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/

WORKDIR /app

# Copy dependency descriptor files first to leverage Docker layer caching
COPY package.json package-lock.json ./
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY backend/pyproject.toml backend/uv.lock ./backend/

# Install dependencies (Node + Python)
RUN npm ci \
  && npm ci --prefix frontend \
  && cd backend && uv sync --frozen

# Copy project source code
COPY . .

EXPOSE 3000 5001

# Start both frontend and backend simultaneously (development mode)
CMD ["npm", "run", "dev"]