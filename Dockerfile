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
FROM python:3.14-slim AS runtime
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

# Runtime dependencies, resolved straight from backend/pyproject.toml + uv.lock
# so those are the single source of truth (no hand-kept list to drift, as it
# did when defusedxml was added). --frozen fails the build loudly if the lock
# is stale rather than silently installing something else; --no-emit-project
# skips the app package itself (its source is COPYed below); --no-deps on the
# install trusts the already-transitive export. Its own layer, so it caches
# across app-code changes.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes \
        --format requirements-txt -o /tmp/requirements.txt \
    && uv pip install --system --no-deps -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

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
