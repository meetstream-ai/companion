# Meet Companion - single-image deployment.
#
# The API serves the built web UI itself, so one container is the whole
# application. Data (SQLite database, config.json, embedding model cache)
# lives in /data; mount a volume there.
#
#   docker build -t meet-companion .
#   docker run -p 8000:8000 -v meet-companion-data:/data meet-companion
#
# or simply `docker compose up`.

# ---- Web UI -----------------------------------------------------------------
FROM node:22-slim AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Server -----------------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY scripts/ ./scripts/
COPY --from=ui /ui/dist ./frontend/dist

# Everything the container writes goes under /data. APP_ENV=production keeps
# the unauthenticated interactive API docs (/docs) off; API_DOCS=true re-enables.
ENV MEET_COMPANION_CONFIG=/data/config.json \
    DATABASE_URL=sqlite+aiosqlite:////data/meet-companion.db \
    EMBEDDING_CACHE_DIR=/data/models \
    APP_ENV=production \
    APP_HOST=0.0.0.0 \
    PORT=8000
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fsS http://localhost:8000/health || exit 1

# $PORT is what most platforms inject; shell form so it expands.
CMD ["sh", "-c", "uvicorn app.main:app --host ${APP_HOST} --port ${PORT}"]
