# ==============================================================================
# HERMES 2.x - Production Multi-Stage Containerfile
# ==============================================================================

# Stage 1: Frontend Build
FROM node:20-slim AS frontend-builder
WORKDIR /app/gui

# Install dependencies deterministically
COPY gui/package.json gui/package-lock.json ./
RUN npm ci

# Copy source and build production assets
COPY gui/tsconfig.json gui/vite.config.ts gui/index.html ./
COPY gui/src/ ./src/
RUN npm run build

# Stage 2: Runtime Backend
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HERMES_CONTAINER_MODE=true \
    HERMES_DATABASE_PATH=/var/lib/hermes/db/hermes_runtime.db \
    HERMES_KAIROS_DB_PATH=/var/lib/hermes/db/tasks.db \
    HERMES_SESSION_LOG_DIR=/var/lib/hermes/logs/sessions \
    HERMES_REGISTRY_FILE=/var/lib/hermes/registry/recent_workspaces.json \
    HERMES_ARTIFACTS_DIR=/var/lib/hermes/artifacts \
    HERMES_LOGS_DIR=/var/lib/hermes/logs \
    HERMES_EXTERNAL_STORE_DIR=/var/lib/hermes/artifacts/context/tool-results \
    HERMES_BROWSER_ARTIFACTS_DIR=/var/lib/hermes/artifacts/browser \
    HERMES_WORKSPACES_ROOT=/workspaces

# Install minimal OS dependencies for network & git operations, plus Node.js for JS validation
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    nodejs \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create non-root user and persistent directory structure
RUN groupadd -g 1000 hermes && \
    useradd -u 1000 -g hermes -s /bin/bash -m hermes && \
    mkdir -p /var/lib/hermes/db \
             /var/lib/hermes/artifacts \
             /var/lib/hermes/logs/sessions \
             /var/lib/hermes/registry \
             /var/lib/hermes/blobs \
             /workspaces && \
    chown -R hermes:hermes /var/lib/hermes /workspaces

# Install locked Python dependencies & remove build-only setuptools and pip to eliminate CVEs
COPY docker/requirements-linux.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt && \
    pip uninstall -y setuptools pip && \
    rm -rf /usr/local/lib/python3.12/site-packages/pip*

# Copy required application modules explicitly (never COPY . .)
COPY config /app/config
COPY core /app/core
COPY kairos /app/kairos
COPY memory /app/memory
COPY models /app/models
COPY skills /app/skills
COPY tools /app/tools
COPY ui /app/ui
COPY utils /app/utils
COPY docker/entrypoint.sh /app/entrypoint.sh

# Copy compiled frontend from Stage 1
COPY --from=frontend-builder /app/gui/dist /app/gui/dist

RUN chmod +x /app/entrypoint.sh && \
    chown -R hermes:hermes /app

USER hermes

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:8765/api/health || exit 1

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
