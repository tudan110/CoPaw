# -----------------------------------------------------------------------------
# Stage 1: build console frontend (dist not committed in repo).
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim AS console-builder
ARG NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_FETCH_RETRIES=5
ARG NPM_FETCH_RETRY_FACTOR=2
ARG NPM_FETCH_RETRY_MIN_TIMEOUT=20000
ARG NPM_FETCH_RETRY_MAX_TIMEOUT=120000
ARG NPM_FETCH_TIMEOUT=120000
WORKDIR /app
COPY console /app/console
RUN set -eux; \
    cd /app/console; \
    npm config set registry "${NPM_REGISTRY}"; \
    npm config set replace-registry-host "always"; \
    npm config set audit false; \
    npm config set fund false; \
    npm config set fetch-retries "${NPM_FETCH_RETRIES}"; \
    npm config set fetch-retry-factor "${NPM_FETCH_RETRY_FACTOR}"; \
    npm config set fetch-retry-mintimeout "${NPM_FETCH_RETRY_MIN_TIMEOUT}"; \
    npm config set fetch-retry-maxtimeout "${NPM_FETCH_RETRY_MAX_TIMEOUT}"; \
    npm config set fetch-timeout "${NPM_FETCH_TIMEOUT}"; \
    sed -i "s#https://registry.npmjs.org/#${NPM_REGISTRY%/}/#g" package-lock.json; \
    npm ci --include=dev --legacy-peer-deps --no-audit --no-fund --registry="${NPM_REGISTRY}"; \
    export NODE_OPTIONS="--max-old-space-size=4096" && npm run build

# -----------------------------------------------------------------------------
# Stage 2: runtime image with Python, Chromium, and app.
# -----------------------------------------------------------------------------
FROM agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/node:slim

# ENV variables
ENV NODE_ENV=production
ENV WORKSPACE_DIR=/app
ENV QWENPAW_WORKING_DIR=/app/working
ENV QWENPAW_SECRET_DIR=/app/working.secret
ENV QWENPAW_BACKUP_DIR=/app/working.backups

# Channel filtering: use QWENPAW_DISABLED_CHANNELS (exclusion, recommended)
# or QWENPAW_ENABLED_CHANNELS (whitelist). Override at runtime with -e.
ARG QWENPAW_DISABLED_CHANNELS="imessage"
ENV QWENPAW_DISABLED_CHANNELS=${QWENPAW_DISABLED_CHANNELS}
ARG QWENPAW_ENABLED_CHANNELS=""
ENV QWENPAW_ENABLED_CHANNELS=${QWENPAW_ENABLED_CHANNELS}

ARG DEBIAN_FRONTEND=noninteractive
ARG APT_MIRROR=http://mirrors.aliyun.com
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ARG PIP_TRUSTED_HOST=mirrors.aliyun.com
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV UV_INDEX_URL=${PIP_INDEX_URL}
ENV UV_DEFAULT_INDEX=${PIP_INDEX_URL}
ENV PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN set -eux; \
    for apt_source in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
      if [ -f "${apt_source}" ]; then \
        sed -Ei \
          -e "s#https?://deb.debian.org/debian#${APT_MIRROR}/debian#g" \
          -e "s#https?://deb.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
          -e "s#https?://security.debian.org/debian-security#${APT_MIRROR}/debian-security#g" \
          "${apt_source}"; \
      fi; \
    done; \
    printf 'Acquire::Retries \"5\";\nAcquire::http::Timeout \"30\";\nAcquire::https::Timeout \"30\";\n' \
      >/etc/apt/apt.conf.d/99qwenpaw-mirror; \
    apt-get update; \
    apt-get install -y --fix-missing \
      curl \
      ca-certificates \
      python3 \
      python3-pip \
      python3-venv \
      build-essential \
      libssl-dev \
      git \
      supervisor \
      vim \
      gettext-base \
      tesseract-ocr \
      tesseract-ocr-eng \
      tesseract-ocr-chi-sim \
      xfce4 \
      xfce4-terminal \
      xvfb \
      dbus-x11 \
      fonts-wqy-zenhei \
      fonts-wqy-microhei \
      chromium \
      chromium-sandbox \
      libx11-xcb1 \
      libxcomposite1 \
      libxdamage1 \
      libxext6 \
      libxfixes3 \
      libxi6 \
      libxtst6 \
      libnss3 \
      libglib2.0-0 \
      libdrm2 \
      libgbm1 \
      libasound2 \
      fonts-liberation \
      libu2f-udev; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get clean


RUN sed -i 's/^CHROMIUM_FLAGS=""/CHROMIUM_FLAGS="--no-sandbox"/' /usr/bin/chromium

# Playwright: use system Chromium (already installed above).
ENV PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium
# Avoid Playwright downloading its own browser when executable_path is used.
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
# Indicate running in container (used e.g. for Chromium --no-sandbox).
ENV QWENPAW_RUNNING_IN_CONTAINER=1

WORKDIR ${WORKSPACE_DIR}

RUN python3 -m venv venv
ENV PATH="/app/venv/bin:$PATH"

COPY pyproject.toml setup.py README.md ./
COPY src ./src
# Inject console dist from build stage (repo does not commit dist).
COPY --from=console-builder /app/console/dist/ ./src/qwenpaw/console/
# Speed up Python package installation with uv.
COPY --from=agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/uv:latest /uv /bin/uv

RUN uv pip install --python /app/venv/bin/python --no-cache-dir ".[ollama]" \
  && rm -rf ./build

# Init working dir with default config.json and HEARTBEAT.md (build time).
RUN qwenpaw init --defaults --accept-security

# Copy working directory data to backup (for PVC init on first start)
COPY deploy-all/qwenpaw/data/qwenpaw/ /app/.working.backup/
# Overlay repo-managed extensions into backup working dir
COPY deploy-all/qwenpaw/working/extensions /app/.working.backup/extensions
# Copy workspace skills into the backup workspace
COPY deploy-all/qwenpaw/working/workspaces/query/skills /app/.working.backup/workspaces/query/skills
COPY deploy-all/qwenpaw/working/workspaces/resource/skills /app/.working.backup/workspaces/resource/skills
COPY deploy-all/qwenpaw/working/workspaces/fault/skills /app/.working.backup/workspaces/fault/skills
COPY deploy-all/qwenpaw/working/workspaces/order/skills /app/.working.backup/workspaces/order/skills
COPY deploy-all/qwenpaw/working/workspaces/knowledge/skills /app/.working.backup/workspaces/knowledge/skills
# Copy secret directory data to backup
COPY deploy-all/qwenpaw/data/qwenpaw.secret/ /app/.working.secret.backup/

# Create empty working directories (PVC will mount over these)
RUN mkdir -p /app/working /app/working.secret

# Copy knowledge directory for kb-retriever skill
COPY knowledge/ /app/knowledge/

# QwenPaw app port (default 8088). Override at runtime with -e QWENPAW_PORT=3000.
ENV QWENPAW_PORT=8088

COPY deploy-all/qwenpaw/config/supervisord.conf.template /etc/supervisor/conf.d/supervisord.conf.template
COPY --chmod=755 deploy-all/qwenpaw/entrypoint.sh /entrypoint.sh

EXPOSE 8088

CMD ["/entrypoint.sh"]
