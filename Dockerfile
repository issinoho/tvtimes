# syntax=docker/dockerfile:1
#
# All-in-one tvtimes image: the FastAPI API, the arq worker, and the built web
# app in one container. `docker compose` runs it twice — once as the web/API
# process, once (command: worker) as the background worker.
#
#   docker build -t issinoho1969/tvtimes .
#
# Published multi-arch by .github/workflows/release.yml on a `v*` tag.

# --- stage 1: build the SPA -------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install
COPY frontend/ ./
# Same-origin build: the client talks to /api on whatever host serves it.
RUN npm run build

# --- stage 2: python runtime --------------------------------------------------
FROM python:3.12-slim AS runtime
# Release tag, passed by .github/workflows/release.yml; "dev" for a plain build.
ARG TVTIMES_VERSION=dev
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    TVTIMES_STATIC_DIR=/app/web \
    TVTIMES_VERSION=$TVTIMES_VERSION
WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /bin/uv

# gosu lets the entrypoint start as root (to take ownership of a bind-mounted
# /data) and drop to the unprivileged app user before exec'ing anything.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && gosu nobody true

# Runtime dependencies (mirrors backend/pyproject.toml [project.dependencies],
# minus the dev extras). Its own layer so it caches across app-code changes.
RUN uv pip install --system \
        "fastapi>=0.115" "uvicorn[standard]>=0.32" "pydantic>=2.9" "pydantic-settings>=2.6" \
        "sqlalchemy[asyncio]>=2.0.36" "alembic>=1.14" "asyncpg>=0.30" "aiosqlite>=0.20" \
        "greenlet>=3.1" "structlog>=24.4" "httpx>=0.28" "python-multipart>=0.0.12" \
        "email-validator>=2.2" "webauthn>=2.2" "argon2-cffi>=23.1" "pyotp>=2.9" \
        "pyjwt[crypto]>=2.10" "cryptography>=44" "slowapi>=0.1.9" "arq>=0.26" "redis>=5.2"

COPY backend/ ./
COPY --from=web /web/dist ./web
COPY docker/entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint \
    && useradd --system --uid 10001 --home /app tvtimes \
    && mkdir -p /data && chown -R tvtimes:tvtimes /app /data

# No `USER` — the entrypoint starts as root, chowns /data (usually a fresh
# bind mount), then re-execs itself as `tvtimes` via gosu. An operator who
# wants a non-root PID 1 can still set `user:` in compose; the entrypoint
# then skips the chown and fails loudly if /data isn't writable.

EXPOSE 8000
ENTRYPOINT ["entrypoint"]
CMD ["web"]
